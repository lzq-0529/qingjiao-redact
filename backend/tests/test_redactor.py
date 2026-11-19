from __future__ import annotations

import unittest

from app.models import EntitySpan
from app.redactor import (
    assign_placeholders_and_redact,
    merge_human_decisions,
    restore_text,
)


class RedactorTests(unittest.TestCase):
    def test_placeholder_reuse_and_strict_restore(self) -> None:
        text = "原告林嘉禾起诉杭州云帆智能科技有限公司，林嘉禾要求赔偿。"
        entities = [
            EntitySpan(id="1", start=2, end=5, original_text="林嘉禾", entity_type="PERSON"),
            EntitySpan(
                id="2",
                start=7,
                end=19,
                original_text="杭州云帆智能科技有限公司",
                entity_type="ORGANIZATION",
            ),
            EntitySpan(id="3", start=20, end=23, original_text="林嘉禾", entity_type="PERSON"),
        ]

        redacted, assigned, mapping = assign_placeholders_and_redact(text, entities)
        self.assertEqual(
            redacted,
            "原告{{人名_0001}}起诉{{机构_0001}}，{{人名_0001}}要求赔偿。",
        )
        self.assertEqual(
            mapping,
            {
                "{{人名_0001}}": "林嘉禾",
                "{{机构_0001}}": "杭州云帆智能科技有限公司",
            },
        )
        self.assertEqual(len(assigned), 3)

        # Simulate LLM editing text while keeping placeholders.
        llm_reply = "建议 {{人名_0001}} 与 {{机构_0001}} 优先协商解决争议。"
        restored = restore_text(llm_reply, mapping, strict=True)
        self.assertTrue(restored.ok)
        self.assertEqual(
            restored.restored_text,
            "建议 林嘉禾 与 杭州云帆智能科技有限公司 优先协商解决争议。",
        )
        self.assertEqual(restored.replaced_count, 2)

    def test_strict_restore_aborts_on_unknown_placeholder(self) -> None:
        mapping = {"{{人名_0001}}": "林嘉禾"}
        res = restore_text("{{人名_0001}} 和 {{人名_9999}} 签署合同", mapping, strict=True)
        self.assertFalse(res.ok)
        self.assertIsNone(res.restored_text)
        self.assertEqual(res.unmatched_placeholders, ["{{人名_9999}}"])

    def test_mask_and_blackout_modes(self) -> None:
        text = "受访人林嘉禾来自云帆公司"
        entities = [
            EntitySpan(id="1", start=3, end=6, original_text="林嘉禾", entity_type="PERSON"),
            EntitySpan(id="2", start=8, end=12, original_text="云帆公司", entity_type="ORGANIZATION"),
        ]
        masked, _, _ = assign_placeholders_and_redact(text, entities, mode="mask")
        self.assertEqual(masked, "受访人***来自****")

        blacked, _, _ = assign_placeholders_and_redact(text, entities, mode="blackout")
        self.assertEqual(blacked, "受访人███来自████")

    def test_excluded_entity_stays_verbatim_and_survives_rerun(self) -> None:
        text = "原告林嘉禾向杭州市余杭区人民法院起诉。"
        existing = [
            EntitySpan(
                id="1",
                start=2,
                end=5,
                original_text="林嘉禾",
                entity_type="PERSON",
                status="confirmed",
            ),
            EntitySpan(
                id="2",
                start=6,
                end=16,
                original_text="杭州市余杭区人民法院",
                entity_type="ORGANIZATION",
                status="excluded",
            ),
        ]
        fresh = [
            EntitySpan(id="m1", start=2, end=5, original_text="林嘉禾", entity_type="PERSON"),
            EntitySpan(
                id="m2",
                start=6,
                end=16,
                original_text="杭州市余杭区人民法院",
                entity_type="ORGANIZATION",
            ),
        ]
        merged = merge_human_decisions(existing, fresh)
        redacted, _, mapping = assign_placeholders_and_redact(text, merged)
        self.assertEqual(redacted, "原告{{人名_0001}}向杭州市余杭区人民法院起诉。")
        self.assertEqual(mapping, {"{{人名_0001}}": "林嘉禾"})


if __name__ == "__main__":
    unittest.main()
