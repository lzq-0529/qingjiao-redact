#!/usr/bin/env python3
"""Reproducible NER benchmark helper for Qingjiao Redact Community.

Supports evaluating the standalone ModelScope RaNER recognizer on a JSONL dataset
such as CLUENER2020 dev (`{"text": "...", "label": {"name": {...}, "company": {...}}}`)
or custom span JSONL (`{"text": "...", "entities": [{"start": 0, "end": 3, "type": "PERSON"}]}`).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ner import get_recognizer  # noqa: E402
from app.redactor import assign_placeholders_and_redact, restore_text  # noqa: E402

CLUENER_MAP = {
    "name": "PERSON",
    "company": "ORGANIZATION",
    "organization": "ORGANIZATION",
    "government": "ORGANIZATION",
    "address": "LOCATION",
}


def load_gold(path: Path, limit: int | None = None) -> list[tuple[str, set[tuple[int, int, str]]]]:
    rows: list[tuple[str, set[tuple[int, int, str]]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        text = item["text"]
        gold: set[tuple[int, int, str]] = set()
        if "entities" in item:
            for ent in item["entities"]:
                gold.add((int(ent["start"]), int(ent["end"]), str(ent["type"]).upper()))
        elif "label" in item:
            for label_key, mentions in (item.get("label") or {}).items():
                mapped = CLUENER_MAP.get(label_key)
                if not mapped:
                    continue
                for _, ranges in mentions.items():
                    for start, end_inclusive in ranges:
                        gold.add((int(start), int(end_inclusive) + 1, mapped))
        rows.append((text, gold))
        if limit and len(rows) >= limit:
            break
    return rows


def score_dataset(path: Path, limit: int | None = None) -> dict:
    rows = load_gold(path, limit=limit)
    recognizer = get_recognizer()

    stats: dict[str, dict[str, int]] = {
        t: {"gold": 0, "pred": 0, "exact": 0}
        for t in ("PERSON", "ORGANIZATION", "LOCATION")
    }
    restore_exact_count = 0

    t0 = time.perf_counter()
    for text, gold in rows:
        preds = recognizer.detect(text)
        redacted, _, mapping = assign_placeholders_and_redact(text, preds)
        restored = restore_text(redacted, mapping, strict=True)
        if restored.ok and restored.restored_text == text:
            restore_exact_count += 1

        pred_set = {(p.start, p.end, p.entity_type) for p in preds}
        for t in stats:
            g_t = {x for x in gold if x[2] == t}
            p_t = {x for x in pred_set if x[2] == t}
            stats[t]["gold"] += len(g_t)
            stats[t]["pred"] += len(p_t)
            stats[t]["exact"] += len(g_t & p_t)
    elapsed = time.perf_counter() - t0

    summary: dict[str, dict[str, float | int]] = {}
    for t, c in stats.items():
        p = c["exact"] / c["pred"] if c["pred"] else 0.0
        r = c["exact"] / c["gold"] if c["gold"] else 0.0
        f1 = (2 * p * r / (p + r)) if (p + r) else 0.0
        summary[t] = {
            **c,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
        }

    return {
        "engine": recognizer.name,
        "model_id": recognizer.model_id,
        "samples": len(rows),
        "elapsed_sec": round(elapsed, 2),
        "restore_exact_rate": round(restore_exact_count / len(rows), 4) if rows else 1.0,
        "metrics": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Community Edition NER metrics.")
    parser.add_argument("--data", required=True, help="Path to CLUENER dev.json or span JSONL")
    parser.add_argument("--limit", type=int, default=None, help="Optional sample limit")
    args = parser.parse_args()
    result = score_dataset(Path(args.data), limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
