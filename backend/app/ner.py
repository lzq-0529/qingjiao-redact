"""Pure open-source NER recognition layer powered by Alibaba ModelScope RaNER.

Community Edition intentionally ships ONLY the standalone open-source ModelScope
RaNER model (`iic/nlp_raner_named-entity-recognition_chinese-base-news`, 3 entity
types: PERSON, ORGANIZATION, LOCATION) without proprietary rule packs,
commercial recognition engines, or OCR pipelines.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Protocol, cast

from .models import ALL_ENTITY_TYPES, EntitySpan, EntityType
from .regex_rules import detect_basic_regex

DEFAULT_RANER_MODEL = "iic/nlp_raner_named-entity-recognition_chinese-base-news"
NER_ENTITY_TYPES: tuple[EntityType, ...] = ("PERSON", "ORGANIZATION", "LOCATION")

# Mapping from ModelScope RaNER (MSRA schema) labels to normalized community types.
_RANER_TYPE_MAP: dict[str, EntityType] = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "ORGANIZATION": "ORGANIZATION",
    "LOC": "LOCATION",
    "LOCATION": "LOCATION",
    "GPE": "LOCATION",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；\n])")


class EntityRecognizer(Protocol):
    """Pluggable recognizer interface so contributors can test custom NER backbones."""

    name: str
    model_id: str

    def detect(self, text: str) -> list[EntitySpan]:
        ...


def _configure_cache_dir() -> Path:
    configured = os.environ.get("MODELSCOPE_CACHE", "").strip()
    cache = Path(configured) if configured else Path.cwd() / ".model_cache" / "modelscope"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["MODELSCOPE_CACHE"] = str(cache)
    return cache


def _resolve_local_model_path(cache_dir: Path, model_id: str) -> str:
    """Prefer already-cached ModelScope weights so repeated runs work offline."""
    direct = Path(model_id)
    if direct.is_dir():
        return str(direct)
    sanitized = model_id.replace("/", "--")
    candidates = [
        cache_dir / "models" / sanitized / "snapshots" / "master",
        cache_dir / "models" / sanitized,
        cache_dir / "models" / model_id / "snapshots" / "master",
        cache_dir / "models" / model_id,
        cache_dir / "hub" / "models" / model_id,
        cache_dir / "hub" / model_id,
    ]
    for candidate in candidates:
        if any(
            (candidate / marker).exists()
            for marker in ("configuration.json", "config.json", "pytorch_model.bin")
        ):
            return str(candidate)
    return model_id


def _disable_max_length_padding(ner_pipeline: Any) -> None:
    """Avoid padding short chunks up to 512 tokens on CPU."""
    tokenizer = getattr(getattr(ner_pipeline, "preprocessor", None), "nlp_tokenizer", None)
    kwargs = getattr(tokenizer, "tokenize_kwargs", None)
    if isinstance(kwargs, dict):
        kwargs["padding"] = False


def _split_chunks(text: str, max_chunk_size: int) -> list[tuple[str, int]]:
    """Split long text along natural sentence boundaries while preserving exact offsets."""
    chunks: list[tuple[str, int]] = []
    offset = 0
    for paragraph in text.splitlines(keepends=True):
        if len(paragraph) <= max_chunk_size:
            chunks.append((paragraph, offset))
            offset += len(paragraph)
            continue

        buf = ""
        buf_start = offset
        cursor = offset
        for piece in _SENTENCE_SPLIT.split(paragraph):
            if not piece:
                continue
            if len(piece) > max_chunk_size:
                if buf:
                    chunks.append((buf, buf_start))
                    buf = ""
                for pos in range(0, len(piece), max_chunk_size):
                    sub = piece[pos : pos + max_chunk_size]
                    chunks.append((sub, cursor + pos))
                cursor += len(piece)
                buf_start = cursor
                continue
            if buf and len(buf) + len(piece) > max_chunk_size:
                chunks.append((buf, buf_start))
                buf = piece
                buf_start = cursor
            else:
                if not buf:
                    buf_start = cursor
                buf += piece
            cursor += len(piece)
        if buf:
            chunks.append((buf, buf_start))
        offset += len(paragraph)
    return [(c, off) for c, off in chunks if c.strip()]


def _deduplicate_spans(candidates: list[EntitySpan]) -> list[EntitySpan]:
    """Keep regex / longer / higher-confidence non-overlapping spans sorted by offset."""
    selected: list[EntitySpan] = []
    ordered = sorted(
        candidates,
        key=lambda item: (
            0 if item.source == "basic-regex" else 1,
            -(item.end - item.start),
            -item.confidence,
            item.start,
        ),
    )
    for cand in ordered:
        if any(cand.start < existing.end and existing.start < cand.end for existing in selected):
            continue
        selected.append(cand)
    selected.sort(key=lambda item: item.start)
    for idx, item in enumerate(selected, start=1):
        item.id = f"ENT_{idx:04d}"
    return selected


class ModelScopeRaNERRecognizer:
    """Standalone Alibaba ModelScope RaNER recognizer (no commercial regex rules)."""

    name = "modelscope-raner"
    _lock = threading.Lock()
    _cached_pipeline: Any = None
    _cached_model_id: str | None = None

    def __init__(
        self,
        model_id: str | None = None,
        threshold: float = 0.05,
        max_chunk_size: int = 420,
    ) -> None:
        self.model_id = (
            model_id
            or os.environ.get("QINGJIAO_RANER_MODEL", "").strip()
            or DEFAULT_RANER_MODEL
        )
        self.threshold = threshold
        self.max_chunk_size = max_chunk_size
        self._pipeline = self._load_pipeline(self.model_id)

    @classmethod
    def _load_pipeline(cls, model_id: str) -> Any:
        with cls._lock:
            if cls._cached_pipeline is not None and cls._cached_model_id == model_id:
                return cls._cached_pipeline

            cache_dir = _configure_cache_dir()
            try:
                from modelscope.pipelines import pipeline
                from modelscope.utils.constant import Tasks
            except ImportError as exc:
                raise RuntimeError(
                    "ModelScope RaNER runtime is not installed. Run:\n"
                    "  pip install -r backend/requirements-ner.txt\n"
                    "Or set QINGJIAO_NER_ENGINE=demo to preview the UI with sample data."
                ) from exc

            # Limit PyTorch CPU thread contention on multi-core hosts.
            try:
                import torch

                budget = min(4, os.cpu_count() or 1)
                torch.set_num_threads(budget)
            except Exception:
                pass

            resolved_model = _resolve_local_model_path(cache_dir, model_id)
            pipe = pipeline(Tasks.named_entity_recognition, model=resolved_model)
            _disable_max_length_padding(pipe)
            cls._cached_pipeline = pipe
            cls._cached_model_id = model_id
            return pipe

    def detect(self, text: str) -> list[EntitySpan]:
        if not text or not text.strip():
            return []

        if len(text) <= self.max_chunk_size:
            candidates = self._detect_chunk(text, offset=0)
            if _regex_enabled():
                candidates.extend(detect_basic_regex(text))
            return _deduplicate_spans(candidates)

        chunks = _split_chunks(text, self.max_chunk_size)
        overlap = min(64, self.max_chunk_size // 3)
        windows = list(chunks)
        for _, off in chunks[1:]:
            if off > 0 and text[off - 1] not in "\r\n":
                win_start = max(0, off - overlap)
                win_end = min(len(text), off + overlap)
                windows.append((text[win_start:win_end], win_start))

        candidates: list[EntitySpan] = []
        for chunk, off in windows:
            candidates.extend(self._detect_chunk(chunk, offset=off))
        if _regex_enabled():
            candidates.extend(detect_basic_regex(text))
        return _deduplicate_spans(candidates)

    def _detect_chunk(self, chunk: str, offset: int) -> list[EntitySpan]:
        result = cast(dict[str, Any], self._pipeline(chunk))
        spans: list[EntitySpan] = []
        for idx, raw in enumerate(result.get("output") or [], start=1):
            prob = float(raw.get("prob") or 1.0)
            if prob < self.threshold:
                continue
            local_start = int(raw.get("start", -1))
            local_end = int(raw.get("end", -1))
            if not (0 <= local_start < local_end <= len(chunk)):
                continue
            mapped = _RANER_TYPE_MAP.get(str(raw.get("type") or "").upper())
            if mapped not in ALL_ENTITY_TYPES:
                continue
            raw_text = chunk[local_start:local_end]
            trimmed = raw_text.strip()
            if not trimmed:
                continue
            lead = len(raw_text) - len(raw_text.lstrip())
            start = offset + local_start + lead
            end = start + len(trimmed)
            spans.append(
                EntitySpan(
                    id=f"RANER_{idx:04d}",
                    start=start,
                    end=end,
                    original_text=trimmed,
                    entity_type=mapped,
                    confidence=round(min(max(prob, 0.0), 1.0), 4),
                    source=self.name,
                )
            )
        return spans


class DemoSampleRecognizer:
    """Lightweight offline demo recognizer for CI and zero-dependency UI previews.

    Only matches synthetic entity names from the built-in demo documents when
    `QINGJIAO_NER_ENGINE=demo` is explicitly selected. Does NOT contain any
    commercial regex rules.
    """

    name = "demo-preview"
    model_id = "demo-synthetic-samples-only"

    _SAMPLE_ENTITIES: tuple[tuple[str, EntityType], ...] = (
        ("林嘉禾", "PERSON"),
        ("沈知行", "PERSON"),
        ("周明远", "PERSON"),
        ("陈清扬", "PERSON"),
        ("顾清秋", "PERSON"),
        ("陆景川", "PERSON"),
        ("杭州云帆智能科技有限公司", "ORGANIZATION"),
        ("云帆公司", "ORGANIZATION"),
        ("杭州市余杭区人民法院", "ORGANIZATION"),
        ("上海星桥律师事务所", "ORGANIZATION"),
        ("华东算力联合实验室", "ORGANIZATION"),
        ("北京清源数据研究院", "ORGANIZATION"),
        ("青禾医疗科技集团", "ORGANIZATION"),
        ("浙江省杭州市余杭区文一西路969号", "LOCATION"),
        ("上海市静安区南京西路1266号", "LOCATION"),
        ("北京市海淀区中关村东路1号", "LOCATION"),
        ("苏州工业园区星湖街328号", "LOCATION"),
    )

    def detect(self, text: str) -> list[EntitySpan]:
        if not text:
            return []
        candidates: list[EntitySpan] = []
        for term, entity_type in self._SAMPLE_ENTITIES:
            cursor = 0
            while True:
                idx = text.find(term, cursor)
                if idx == -1:
                    break
                candidates.append(
                    EntitySpan(
                        id="DEMO_0000",
                        start=idx,
                        end=idx + len(term),
                        original_text=term,
                        entity_type=entity_type,
                        confidence=0.95,
                        source=self.name,
                    )
                )
                cursor = idx + len(term)
        if _regex_enabled():
            candidates.extend(detect_basic_regex(text))
        return _deduplicate_spans(candidates)


def _regex_enabled() -> bool:
    return os.environ.get("QINGJIAO_ENABLE_REGEX", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


_recognizer_lock = threading.Lock()
_active_recognizer: EntityRecognizer | None = None
_active_engine_key: str | None = None


def get_recognizer() -> EntityRecognizer:
    """Return the configured NER recognizer singleton (defaults to Alibaba RaNER)."""
    global _active_recognizer, _active_engine_key

    engine = os.environ.get("QINGJIAO_NER_ENGINE", "raner").strip().lower()
    model_id = os.environ.get("QINGJIAO_RANER_MODEL", DEFAULT_RANER_MODEL).strip()
    cache_key = f"{engine}:{model_id}"

    with _recognizer_lock:
        if _active_recognizer is not None and _active_engine_key == cache_key:
            return _active_recognizer

        if engine == "demo":
            recognizer: EntityRecognizer = DemoSampleRecognizer()
        elif engine == "raner":
            recognizer = ModelScopeRaNERRecognizer(model_id=model_id)
        else:
            raise ValueError(
                f"Unsupported QINGJIAO_NER_ENGINE={engine!r}. Use 'raner' or 'demo'."
            )

        _active_recognizer = recognizer
        _active_engine_key = cache_key
        return recognizer


def reset_recognizer_cache() -> None:
    """Reset cached recognizer (primarily used by unit tests)."""
    global _active_recognizer, _active_engine_key
    with _recognizer_lock:
        _active_recognizer = None
        _active_engine_key = None


def runtime_engine_status() -> dict[str, Any]:
    """Inspect whether ModelScope RaNER dependencies are available."""
    engine = os.environ.get("QINGJIAO_NER_ENGINE", "raner").strip().lower()
    model_id = os.environ.get("QINGJIAO_RANER_MODEL", DEFAULT_RANER_MODEL).strip()
    try:
        import modelscope  # noqa: F401

        modelscope_installed = True
    except Exception:
        modelscope_installed = False

    return {
        "edition": "community",
        "configured_engine": engine,
        "model_id": DEFAULT_RANER_MODEL if engine == "raner" else model_id,
        "modelscope_installed": modelscope_installed,
        "supported_entity_types": list(ALL_ENTITY_TYPES),
        "rules_enabled": _regex_enabled(),
        "notes": (
            "开源版搭载阿里 ModelScope RaNER + 5 类基础正则规则（共 8 类实体）。"
            "如需 30+ 敏感字段、高精度自研引擎、PDF/Excel/OCR 与一键桌面安装包，请访问 https://qingjiaolab.com。"
        ),
    }
