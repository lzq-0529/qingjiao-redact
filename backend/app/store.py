"""Simple local JSON file store for document sessions and source DOCX files."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .models import DocumentSession

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class SessionStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        configured = os.environ.get("QINGJIAO_DATA_DIR", "").strip()
        root = base_dir or (Path(configured) if configured else Path.cwd() / "data")
        self.sessions_dir = root / "sessions"
        self.blobs_dir = root / "blobs"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_id(session_id: str) -> str:
        if not _SAFE_ID.match(session_id):
            raise ValueError("Invalid session_id")
        return session_id

    def save(self, session: DocumentSession) -> DocumentSession:
        sid = self._validate_id(session.session_id)
        path = self.sessions_dir / f"{sid}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
        return session

    def get(self, session_id: str) -> DocumentSession | None:
        sid = self._validate_id(session_id)
        path = self.sessions_dir / f"{sid}.json"
        if not path.is_file():
            return None
        return DocumentSession.model_validate_json(path.read_text(encoding="utf-8"))

    def list_all(self) -> list[DocumentSession]:
        sessions: list[DocumentSession] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                sessions.append(
                    DocumentSession.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        sid = self._validate_id(session_id)
        path = self.sessions_dir / f"{sid}.json"
        blob = self.blobs_dir / f"{sid}.docx"
        existed = path.is_file()
        if existed:
            path.unlink()
        if blob.is_file():
            blob.unlink()
        return existed

    def save_docx_blob(self, session_id: str, content: bytes) -> None:
        sid = self._validate_id(session_id)
        (self.blobs_dir / f"{sid}.docx").write_bytes(content)

    def get_docx_blob(self, session_id: str) -> bytes | None:
        sid = self._validate_id(session_id)
        path = self.blobs_dir / f"{sid}.docx"
        return path.read_bytes() if path.is_file() else None
