"""Command-line interface for Qingjiao Redact Community."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .doc_io import build_redacted_docx, build_restored_docx, extract_text_from_bytes
from .models import ALL_ENTITY_TYPES
from .ner import get_recognizer
from .redactor import assign_placeholders_and_redact, restore_text


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_redact(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    raw = input_path.read_bytes()
    fmt, text = extract_text_from_bytes(input_path.name, raw)

    recognizer = get_recognizer()
    entities = recognizer.detect(text)
    redacted, assigned, mapping = assign_placeholders_and_redact(
        text,
        entities,
        mode=args.mode,
        enabled_types=list(ALL_ENTITY_TYPES),
    )

    out_path = Path(args.output)
    if fmt == "docx" and out_path.suffix.lower() == ".docx":
        out_path.write_bytes(build_redacted_docx(raw, assigned, mode=args.mode))
    else:
        out_path.write_text(redacted, encoding="utf-8")

    map_path = Path(args.map) if args.map else out_path.with_suffix(".map.json")
    map_path.write_text(
        json.dumps(
            {
                "source": input_path.name,
                "mode": args.mode,
                "engine": recognizer.name,
                "model_id": recognizer.model_id,
                "mapping": mapping,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Redacted {len(mapping)} unique entities -> {out_path} (mapping: {map_path})")
    return 0


def _cmd_restore(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    map_data = json.loads(Path(args.map).read_text(encoding="utf-8"))
    mapping = map_data.get("mapping") if isinstance(map_data, dict) else {}
    out_path = Path(args.output)

    if input_path.suffix.lower() == ".docx":
        restored_bytes, unmatched, replaced = build_restored_docx(
            input_path.read_bytes(), mapping, strict=not args.allow_partial
        )
        if restored_bytes is None:
            print(f"Restore aborted. Unmatched placeholders: {', '.join(unmatched)}", file=sys.stderr)
            return 1
        out_path.write_bytes(restored_bytes)
        print(f"Restored {replaced} placeholders -> {out_path}")
        return 0

    result = restore_text(
        input_path.read_text(encoding="utf-8"),
        mapping,
        strict=not args.allow_partial,
    )
    if not result.ok or result.restored_text is None:
        print(result.error or "Restore failed", file=sys.stderr)
        return 1
    out_path.write_text(result.restored_text, encoding="utf-8")
    print(f"Restored {result.replaced_count} placeholders -> {out_path}")
    return 0


def _cmd_mcp(_args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    return mcp_main()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qingjiao-redact",
        description="Qingjiao Redact Community CLI (local Chinese NER redaction & restore).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Start the local web workbench server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_redact = sub.add_parser("redact", help="Redact a local TXT, Markdown, or DOCX file")
    p_redact.add_argument("input", help="Source file path")
    p_redact.add_argument("-o", "--output", required=True, help="Redacted output file path")
    p_redact.add_argument("-m", "--map", help="Mapping JSON path (default: <output>.map.json)")
    p_redact.add_argument(
        "--mode", choices=["placeholder", "mask", "blackout"], default="placeholder"
    )
    p_redact.set_defaults(func=_cmd_redact)

    p_restore = sub.add_parser("restore", help="Strictly restore placeholders back to originals")
    p_restore.add_argument("input", help="Redacted or AI-edited file path")
    p_restore.add_argument("-m", "--map", required=True, help="Mapping JSON file path")
    p_restore.add_argument("-o", "--output", required=True, help="Restored output file path")
    p_restore.add_argument("--allow-partial", action="store_true")
    p_restore.set_defaults(func=_cmd_restore)

    p_mcp = sub.add_parser("mcp", help="Run the stdio MCP privacy server")
    p_mcp.set_defaults(func=_cmd_mcp)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
