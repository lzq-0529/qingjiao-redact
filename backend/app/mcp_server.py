"""Standalone JSON-RPC 2.0 stdio MCP Server for Qingjiao Redact Community.

Use this server with Cursor, Claude Desktop, Windsurf, or any MCP-compatible
agent so sensitive Chinese entities (Person, Organization, Location) are redacted
locally BEFORE prompts leave your machine, and strictly restored afterwards.

Run:
    python -m app.mcp_server
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .models import ALL_ENTITY_TYPES, DocumentSession, EntityType, RedactionMode
from .ner import get_recognizer, runtime_engine_status
from .redactor import assign_placeholders_and_redact, restore_text
from .store import SessionStore

MAX_LINE_BYTES = 2_000_000

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "redact_text",
        "description": (
            "Locally redact Chinese PERSON, ORGANIZATION, and LOCATION entities using "
            "Alibaba ModelScope RaNER and store a reversible placeholder mapping locally. "
            "Returns redacted_text and session_id for later restoration."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Original Chinese text to redact locally.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["placeholder", "mask", "blackout"],
                    "default": "placeholder",
                    "description": "placeholder (reversible), mask (***), or blackout (███).",
                },
                "enabled_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(ALL_ENTITY_TYPES)},
                    "default": list(ALL_ENTITY_TYPES),
                },
                "title": {
                    "type": "string",
                    "default": "MCP 会话脱敏",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "restore_text",
        "description": (
            "Strictly restore placeholders (e.g. {{人名_0001}}) in an LLM response back "
            "to original verbatim values using a previously created local session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID returned by redact_text.",
                },
                "text": {
                    "type": "string",
                    "description": "AI-generated text containing placeholders to restore.",
                },
                "strict": {
                    "type": "boolean",
                    "default": True,
                    "description": "Abort if any unknown placeholder is encountered.",
                },
            },
            "required": ["session_id", "text"],
        },
    },
    {
        "name": "list_sessions",
        "description": "List locally saved redaction sessions available for restoration.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_capabilities",
        "description": "Return current Community Edition NER engine status and supported entity types.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _execute_tool(name: str, arguments: dict[str, Any], store: SessionStore) -> dict[str, Any]:
    if name == "get_capabilities":
        return {"version": __version__, **runtime_engine_status()}

    if name == "list_sessions":
        sessions = store.list_all()[:30]
        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "mode": s.mode,
                    "mapping_count": len(s.mapping),
                    "updated_at": s.updated_at,
                }
                for s in sessions
            ]
        }

    if name == "redact_text":
        text = str(arguments.get("text") or "")
        if not text.strip():
            raise ValueError("text must be a non-empty string")
        mode: RedactionMode = arguments.get("mode") or "placeholder"
        if mode not in ("placeholder", "mask", "blackout"):
            raise ValueError(f"Invalid mode: {mode}")
        raw_types = arguments.get("enabled_types") or list(ALL_ENTITY_TYPES)
        enabled_types: list[EntityType] = [
            t for t in raw_types if t in ALL_ENTITY_TYPES
        ] or list(ALL_ENTITY_TYPES)

        recognizer = get_recognizer()
        t0 = time.perf_counter()
        raw_entities = recognizer.detect(text)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        redacted, entities, mapping = assign_placeholders_and_redact(
            text, raw_entities, mode=mode, enabled_types=enabled_types
        )
        sid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        session = DocumentSession(
            session_id=sid,
            title=str(arguments.get("title") or "MCP 会话脱敏"),
            filename="mcp-input.txt",
            format="txt",
            mode=mode,
            enabled_types=enabled_types,
            source_text=text,
            redacted_text=redacted,
            entities=entities,
            mapping=mapping,
            engine=recognizer.name,
            model_id=recognizer.model_id,
            elapsed_ms=elapsed_ms,
            created_at=now,
            updated_at=now,
        )
        store.save(session)
        return {
            "session_id": sid,
            "mode": mode,
            "engine": recognizer.name,
            "entity_count": len([e for e in entities if e.placeholder]),
            "redacted_text": redacted,
            "placeholders": sorted(mapping.keys()),
        }

    if name == "restore_text":
        session_id = str(arguments.get("session_id") or "")
        text = str(arguments.get("text") or "")
        strict = bool(arguments.get("strict", True))
        session = store.get(session_id)
        if session is None:
            raise ValueError(f"Unknown session_id: {session_id}")
        result = restore_text(text, session.mapping, strict=strict)
        return result.model_dump()

    raise ValueError(f"Unknown tool: {name}")


def handle_message(message: dict[str, Any], store: SessionStore) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    request_id = message.get("id")
    if request_id is None:
        return None  # Notifications require no reply.

    method = message.get("method")
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}

    if method == "initialize":
        response["result"] = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "qingjiao-redact-community", "version": __version__},
        }
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": TOOL_SCHEMAS}
    elif method == "tools/call":
        params = message.get("params") or {}
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        try:
            payload = _execute_tool(tool_name, arguments, store)
            response["result"] = {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
            }
        except Exception as exc:
            response["result"] = {
                "isError": True,
                "content": [{"type": "text", "text": str(exc)}],
            }
    else:
        response["error"] = {"code": -32601, "message": f"Method not found: {method}"}

    return response


def main() -> int:
    store = SessionStore()
    while True:
        raw_line = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
        if not raw_line:
            return 0
        if len(raw_line) > MAX_LINE_BYTES:
            return 2
        try:
            message = json.loads(raw_line)
            reply = handle_message(message, store)
        except Exception:
            reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if reply is not None:
            print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
