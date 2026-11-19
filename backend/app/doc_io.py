"""Lightweight TXT, Markdown, and DOCX I/O for Community Edition."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from docx import Document

from .models import EntitySpan, RedactionMode
from .redactor import PLACEHOLDER_PATTERN

SupportedFormat = Literal["txt", "md", "docx"]


def detect_format(filename: str) -> SupportedFormat:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix in (".md", ".markdown"):
        return "md"
    if suffix in (".txt", ".csv", ".log", ".json", ""):
        return "txt"
    raise ValueError(
        f"社区版仅支持 TXT、Markdown、DOCX 格式（当前文件：{suffix}）。"
        "如需 PDF、扫描件 OCR、Excel、PowerPoint、图片与印章涂黑，请访问 https://qingjiaolab.com 体验商业版。"
    )


def extract_text_from_bytes(filename: str, content: bytes) -> tuple[SupportedFormat, str]:
    fmt = detect_format(filename)
    if fmt == "docx":
        doc = Document(io.BytesIO(content))
        blocks: list[str] = []
        for para in doc.paragraphs:
            if para.text:
                blocks.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    blocks.append("\t".join(row_cells))
        return fmt, "\n".join(blocks)

    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return fmt, content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return fmt, content.decode("utf-8", errors="replace")


def _apply_replacements_to_text(
    text: str,
    replacements: list[tuple[str, str]],
) -> str:
    result = text
    for original, replacement in replacements:
        if original:
            result = result.replace(original, replacement)
    return result


def build_redacted_docx(
    original_docx: bytes,
    entities: list[EntitySpan],
    *,
    mode: RedactionMode = "placeholder",
) -> bytes:
    """Create a redacted DOCX copy by replacing active entity strings in paragraphs and tables."""
    active = [e for e in entities if e.status != "excluded" and e.placeholder]
    # Replace longer originals first to avoid partial substring corruption.
    seen: dict[str, str] = {}
    for entity in sorted(active, key=lambda e: -len(e.original_text)):
        if entity.original_text in seen:
            continue
        if mode == "placeholder":
            token = entity.placeholder
        else:
            char = "█" if mode == "blackout" else "*"
            token = "".join(ch if ch.isspace() else char for ch in entity.original_text)
        seen[entity.original_text] = token
    replacements = list(seen.items())

    doc = Document(io.BytesIO(original_docx))
    for para in doc.paragraphs:
        if para.text:
            updated = _apply_replacements_to_text(para.text, replacements)
            if updated != para.text:
                para.text = updated

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    if para.text:
                        updated = _apply_replacements_to_text(para.text, replacements)
                        if updated != para.text:
                            para.text = updated

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def build_restored_docx(
    redacted_docx: bytes,
    mapping: dict[str, str],
    *,
    strict: bool = True,
) -> tuple[bytes | None, list[str], int]:
    """Restore placeholders inside a DOCX file back to original strings."""
    doc = Document(io.BytesIO(redacted_docx))
    unmatched: set[str] = set()
    all_paragraphs = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paragraphs.extend(cell.paragraphs)

    for para in all_paragraphs:
        for match in PLACEHOLDER_PATTERN.finditer(para.text):
            token = match.group(0)
            if token not in mapping:
                unmatched.add(token)

    if strict and unmatched:
        return None, sorted(unmatched), 0

    replaced = 0

    def _sub(match):
        nonlocal replaced
        token = match.group(0)
        if token in mapping:
            replaced += 1
            return mapping[token]
        return token

    for para in all_paragraphs:
        if PLACEHOLDER_PATTERN.search(para.text):
            para.text = PLACEHOLDER_PATTERN.sub(_sub, para.text)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), sorted(unmatched), replaced
