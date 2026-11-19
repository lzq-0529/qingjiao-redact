"""FastAPI backend for Qingjiao Redact Community."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .doc_io import build_redacted_docx, build_restored_docx, extract_text_from_bytes
from .models import (
    ALL_ENTITY_TYPES,
    ENTITY_LABELS,
    AddManualEntityRequest,
    AnalyzeRequest,
    DocumentSession,
    EntitySpan,
    EntityType,
    RedactionMode,
    RestoreRequest,
    RestoreResponse,
    UpdateSessionRequest,
)
from .ner import get_recognizer, runtime_engine_status
from .redactor import (
    assign_placeholders_and_redact,
    merge_human_decisions,
    restore_text,
)
from .samples import SAMPLES
from .store import SessionStore

BENCHMARK_SUMMARY = {
    "community": {
        "name": "青椒开源社区版（Community）",
        "model": "阿里 ModelScope RaNER (base-news，纯模型，无商业规则)",
        "model_size": "~400 MB (PyTorch)",
        "entity_types_count": "3 类（人名 / 机构 / 地名）",
        "cluener_person_f1": 0.790,
        "cluener_org_f1": 0.713,
        "cluener_org_cover_recall": 0.730,
        "cpu_speed": "单篇长文 ~55.3 s（约 0.8 s/块）",
        "formats": "TXT / Markdown / 基础 DOCX",
        "ocr_and_image": "不支持",
        "deployment": "源码自部署 / Docker",
    },
    "pro": {
        "name": "青椒智能脱敏商业版（Desktop / Pro）",
        "model": "青椒自研高精度本地识别引擎 + 全套结构化校验规则引擎",
        "model_size": "轻量级本地推理引擎（无需 GPU）",
        "entity_types_count": "30+ 类敏感字段 + 4 类图像敏感区",
        "real_doc_10type_f1": 0.919,
        "product_pipeline_f1": 0.923,
        "real_doc_person_f1": 0.982,
        "real_doc_org_f1": 0.942,
        "structured_fields_f1": 0.959,
        "cpu_speed": "0.45 秒 / 千字（CPU 8 线程，无需 GPU）",
        "formats": "Word / Excel / PPT / PDF（原位替换 & 真涂黑）/ 扫描件 OCR / 图片",
        "ocr_and_image": "支持本地/云端 OCR、印章/手写签名/二维码/Logo 识别涂黑",
        "deployment": "Windows / macOS / Linux 一键安装包 + 批量文件夹处理",
        "website": "https://qingjiaolab.com",
        "online_demo": "https://app.qingjiaolab.com",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_enabled_types(raw: str | None) -> list[EntityType]:
    if not raw:
        return list(ALL_ENTITY_TYPES)
    selected: list[EntityType] = []
    for part in raw.split(","):
        token = part.strip().upper()
        if token in ALL_ENTITY_TYPES and token not in selected:
            selected.append(token)  # type: ignore[arg-type]
    return selected or list(ALL_ENTITY_TYPES)


def create_app(store: SessionStore | None = None) -> FastAPI:
    app = FastAPI(
        title="Qingjiao Redact Community API",
        version=__version__,
        description=(
            "Open-source local Chinese NER redaction, human review, reversible restore, "
            "and MCP privacy gateway powered by Alibaba ModelScope RaNER."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    session_store = store or SessionStore()
    app.state.store = session_store

    def _run_analysis(
        *,
        source_text: str,
        title: str,
        filename: str,
        fmt: str,
        mode: RedactionMode,
        enabled_types: list[EntityType],
        docx_bytes: bytes | None = None,
    ) -> DocumentSession:
        try:
            recognizer = get_recognizer()
            t0 = time.perf_counter()
            raw_entities = recognizer.detect(source_text)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        redacted, entities, mapping = assign_placeholders_and_redact(
            source_text,
            raw_entities,
            mode=mode,
            enabled_types=enabled_types,
        )
        sid = uuid.uuid4().hex[:12]
        now = _now_iso()
        session = DocumentSession(
            session_id=sid,
            title=title or filename,
            filename=filename,
            format=fmt,  # type: ignore[arg-type]
            mode=mode,
            enabled_types=enabled_types,
            source_text=source_text,
            redacted_text=redacted,
            entities=entities,
            mapping=mapping,
            engine=recognizer.name,
            model_id=recognizer.model_id,
            elapsed_ms=elapsed_ms,
            created_at=now,
            updated_at=now,
        )
        session_store.save(session)
        if docx_bytes is not None:
            session_store.save_docx_blob(sid, docx_bytes)
        return session

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, **runtime_engine_status()}

    @app.get("/api/capabilities")
    def capabilities() -> dict:
        return {
            "version": __version__,
            "engine": runtime_engine_status(),
            "entity_labels": ENTITY_LABELS,
            "benchmarks": BENCHMARK_SUMMARY,
        }

    @app.get("/api/samples")
    def list_samples() -> dict:
        return {"samples": SAMPLES}

    @app.get("/api/sessions")
    def list_sessions() -> dict:
        sessions = session_store.list_all()
        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "filename": s.filename,
                    "format": s.format,
                    "mode": s.mode,
                    "engine": s.engine,
                    "entity_count": sum(1 for e in s.entities if e.status != "excluded" and e.placeholder),
                    "updated_at": s.updated_at,
                }
                for s in sessions
            ]
        }

    @app.post("/api/sessions/analyze", response_model=DocumentSession)
    def analyze_text(req: AnalyzeRequest) -> DocumentSession:
        return _run_analysis(
            source_text=req.text,
            title=req.title,
            filename=req.filename,
            fmt="md" if req.filename.lower().endswith(".md") else "txt",
            mode=req.mode,
            enabled_types=req.enabled_types,
        )

    @app.post("/api/sessions/upload", response_model=DocumentSession)
    async def upload_document(
        file: UploadFile = File(...),
        mode: RedactionMode = Form("placeholder"),
        enabled_types: str = Form("PERSON,ORGANIZATION,LOCATION"),
    ) -> DocumentSession:
        raw = await file.read()
        if not raw:
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(raw) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="社区版单文件上限为 10 MB")
        filename = file.filename or "upload.txt"
        try:
            fmt, text = extract_text_from_bytes(filename, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not text.strip():
            raise HTTPException(status_code=400, detail="未能从文件中提取到可识别文本")

        return _run_analysis(
            source_text=text,
            title=Path(filename).stem or filename,
            filename=filename,
            fmt=fmt,
            mode=mode,
            enabled_types=_parse_enabled_types(enabled_types),
            docx_bytes=raw if fmt == "docx" else None,
        )

    @app.get("/api/sessions/{session_id}", response_model=DocumentSession)
    def get_session(session_id: str) -> DocumentSession:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")
        return session

    @app.patch("/api/sessions/{session_id}", response_model=DocumentSession)
    def update_session(session_id: str, req: UpdateSessionRequest) -> DocumentSession:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")

        mode = req.mode or session.mode
        enabled_types = req.enabled_types if req.enabled_types is not None else session.enabled_types
        entities_input = req.entities if req.entities is not None else session.entities

        redacted, entities, mapping = assign_placeholders_and_redact(
            session.source_text,
            entities_input,
            mode=mode,
            enabled_types=enabled_types,
        )
        updated = session.model_copy(
            update={
                "mode": mode,
                "enabled_types": enabled_types,
                "entities": entities,
                "redacted_text": redacted,
                "mapping": mapping,
                "updated_at": _now_iso(),
            }
        )
        return session_store.save(updated)

    @app.post("/api/sessions/{session_id}/entities", response_model=DocumentSession)
    def add_manual_entity(session_id: str, req: AddManualEntityRequest) -> DocumentSession:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")
        if not (0 <= req.start < req.end <= len(session.source_text)):
            raise HTTPException(status_code=400, detail="划词范围超出原文边界")
        snippet = session.source_text[req.start : req.end]
        if not snippet.strip():
            raise HTTPException(status_code=400, detail="不能添加空白片段")

        new_span = EntitySpan(
            id="MANUAL_NEW",
            start=req.start,
            end=req.end,
            original_text=snippet,
            entity_type=req.entity_type,
            confidence=1.0,
            source="manual",
            status="confirmed",
            manual=True,
        )
        redacted, entities, mapping = assign_placeholders_and_redact(
            session.source_text,
            [*session.entities, new_span],
            mode=session.mode,
            enabled_types=session.enabled_types,
        )
        updated = session.model_copy(
            update={
                "entities": entities,
                "redacted_text": redacted,
                "mapping": mapping,
                "updated_at": _now_iso(),
            }
        )
        return session_store.save(updated)

    @app.post("/api/sessions/{session_id}/rerun", response_model=DocumentSession)
    def rerun_recognition(session_id: str) -> DocumentSession:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")
        try:
            recognizer = get_recognizer()
            t0 = time.perf_counter()
            proposals = recognizer.detect(session.source_text)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        merged = merge_human_decisions(session.entities, proposals)
        redacted, entities, mapping = assign_placeholders_and_redact(
            session.source_text,
            merged,
            mode=session.mode,
            enabled_types=session.enabled_types,
        )
        updated = session.model_copy(
            update={
                "entities": entities,
                "redacted_text": redacted,
                "mapping": mapping,
                "engine": recognizer.name,
                "model_id": recognizer.model_id,
                "elapsed_ms": elapsed_ms,
                "updated_at": _now_iso(),
            }
        )
        return session_store.save(updated)

    @app.post("/api/sessions/{session_id}/restore", response_model=RestoreResponse)
    def restore_session_text(session_id: str, req: RestoreRequest) -> RestoreResponse:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")
        return restore_text(req.text, session.mapping, strict=req.strict)

    @app.post("/api/sessions/{session_id}/restore-docx")
    async def restore_session_docx(
        session_id: str,
        file: UploadFile = File(...),
        strict: bool = Form(True),
    ) -> Response:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")
        raw = await file.read()
        if not (file.filename or "").lower().endswith(".docx"):
            raise HTTPException(status_code=400, detail="请上传 .docx 文件")
        restored_bytes, unmatched, replaced = build_restored_docx(
            raw, session.mapping, strict=strict
        )
        if restored_bytes is None:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "unmatched_placeholders": unmatched,
                    "error": "文档中存在未匹配占位符，已中止还原：" + "、".join(unmatched),
                },
            )
        out_name = f"{Path(file.filename or 'restored.docx').stem}-已还原.docx"
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}",
            "X-Restored-Count": str(replaced),
        }
        return Response(
            content=restored_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=headers,
        )

    @app.get("/api/sessions/{session_id}/export")
    def export_session(session_id: str, kind: str = "redacted") -> Response:
        session = session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")

        stem = Path(session.filename).stem or session.title
        if kind == "mapping":
            payload = {
                "session_id": session.session_id,
                "filename": session.filename,
                "mode": session.mode,
                "engine": session.engine,
                "model_id": session.model_id,
                "mapping": session.mapping,
            }
            out_name = f"{stem}-映射表.json"
            return JSONResponse(
                content=payload,
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}"},
            )

        if session.format == "docx":
            blob = session_store.get_docx_blob(session_id)
            if blob is not None:
                redacted_docx = build_redacted_docx(blob, session.entities, mode=session.mode)
                out_name = f"{stem}-已脱敏.docx"
                return Response(
                    content=redacted_docx,
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={
                        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}"
                    },
                )

        ext = ".md" if session.format == "md" else ".txt"
        out_name = f"{stem}-已脱敏{ext}"
        return Response(
            content=session.redacted_text.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(out_name)}"},
        )

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: str) -> dict:
        deleted = session_store.delete(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="未找到该脱敏会话")
        return {"deleted": True, "session_id": session_id}

    # Serve built React frontend if present.
    static_candidates = [
        Path(os.environ["QINGJIAO_STATIC_DIR"])
        if os.environ.get("QINGJIAO_STATIC_DIR")
        else None,
        Path(__file__).resolve().parents[2] / "frontend" / "dist",
        Path(__file__).resolve().parent / "static",
    ]
    static_dir = next((p for p in static_candidates if p and (p / "index.html").is_file()), None)
    if static_dir is not None:
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/", include_in_schema=False)
        def serve_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
