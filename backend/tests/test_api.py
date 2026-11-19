from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.ner import reset_recognizer_cache
from app.store import SessionStore


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_engine = os.environ.get("QINGJIAO_NER_ENGINE")
        os.environ["QINGJIAO_NER_ENGINE"] = "demo"
        reset_recognizer_cache()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.tmpdir.name))
        self.client = TestClient(create_app(store=self.store))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        if self._old_engine is None:
            os.environ.pop("QINGJIAO_NER_ENGINE", None)
        else:
            os.environ["QINGJIAO_NER_ENGINE"] = self._old_engine
        reset_recognizer_cache()

    def test_analyze_review_manual_and_restore_flow(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["edition"], "community")

        res = self.client.post(
            "/api/sessions/analyze",
            json={
                "title": "起诉状测试",
                "text": "原告林嘉禾起诉杭州云帆智能科技有限公司，代理人周明远。",
                "mode": "placeholder",
            },
        )
        self.assertEqual(res.status_code, 200)
        session = res.json()
        sid = session["session_id"]
        self.assertIn("{{人名_0001}}", session["redacted_text"])
        self.assertIn("{{机构_0001}}", session["redacted_text"])

        # Add manual entity on "原告"
        manual = self.client.post(
            f"/api/sessions/{sid}/entities",
            json={"start": 0, "end": 2, "entity_type": "PERSON"},
        )
        self.assertEqual(manual.status_code, 200)
        self.assertIn("原告", manual.json()["mapping"].values())

        # Restore AI response strictly
        updated_mapping = manual.json()["mapping"]
        lin_token = next(k for k, v in updated_mapping.items() if v == "林嘉禾")
        org_token = next(
            k for k, v in updated_mapping.items() if v == "杭州云帆智能科技有限公司"
        )
        restored = self.client.post(
            f"/api/sessions/{sid}/restore",
            json={"text": f"核验结果：{lin_token} 与 {org_token} 存在合同纠纷。", "strict": True},
        )
        self.assertEqual(restored.status_code, 200)
        body = restored.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["restored_text"], "核验结果：林嘉禾 与 杭州云帆智能科技有限公司 存在合同纠纷。")

        # Export redacted & mapping
        exp_txt = self.client.get(f"/api/sessions/{sid}/export?kind=redacted")
        self.assertEqual(exp_txt.status_code, 200)
        exp_map = self.client.get(f"/api/sessions/{sid}/export?kind=mapping")
        self.assertEqual(exp_map.status_code, 200)
        self.assertIn("mapping", exp_map.json())

    def test_upload_rejects_pdf_with_upgrade_hint(self) -> None:
        res = self.client.post(
            "/api/sessions/upload",
            files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("qingjiaolab.com", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
