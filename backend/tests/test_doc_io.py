from __future__ import annotations

import io
import unittest

from docx import Document

from app.doc_io import (
    build_redacted_docx,
    build_restored_docx,
    detect_format,
    extract_text_from_bytes,
)
from app.models import EntitySpan
from app.redactor import assign_placeholders_and_redact


class DocIOTests(unittest.TestCase):
    def test_reject_unsupported_commercial_formats(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            detect_format("contract.pdf")
        self.assertIn("qingjiaolab.com", str(ctx.exception))

    def test_docx_round_trip(self) -> None:
        doc = Document()
        doc.add_paragraph("原告：林嘉禾")
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "被告机构"
        table.cell(0, 1).text = "杭州云帆智能科技有限公司"
        buf = io.BytesIO()
        doc.save(buf)
        raw = buf.getvalue()

        fmt, extracted = extract_text_from_bytes("demo.docx", raw)
        self.assertEqual(fmt, "docx")
        self.assertIn("林嘉禾", extracted)
        self.assertIn("杭州云帆智能科技有限公司", extracted)

        spans = [
            EntitySpan(
                id="1",
                start=extracted.index("林嘉禾"),
                end=extracted.index("林嘉禾") + 3,
                original_text="林嘉禾",
                entity_type="PERSON",
            ),
            EntitySpan(
                id="2",
                start=extracted.index("杭州云帆智能科技有限公司"),
                end=extracted.index("杭州云帆智能科技有限公司") + 12,
                original_text="杭州云帆智能科技有限公司",
                entity_type="ORGANIZATION",
            ),
        ]
        _, assigned, mapping = assign_placeholders_and_redact(extracted, spans)
        redacted_docx = build_redacted_docx(raw, assigned, mode="placeholder")
        _, redacted_text = extract_text_from_bytes("redacted.docx", redacted_docx)
        self.assertIn("{{人名_0001}}", redacted_text)
        self.assertIn("{{机构_0001}}", redacted_text)
        self.assertNotIn("林嘉禾", redacted_text)

        restored_docx, unmatched, replaced = build_restored_docx(
            redacted_docx, mapping, strict=True
        )
        self.assertIsNotNone(restored_docx)
        self.assertEqual(unmatched, [])
        self.assertEqual(replaced, 2)
        _, restored_text = extract_text_from_bytes("restored.docx", restored_docx or b"")
        self.assertIn("林嘉禾", restored_text)
        self.assertIn("杭州云帆智能科技有限公司", restored_text)


if __name__ == "__main__":
    unittest.main()
