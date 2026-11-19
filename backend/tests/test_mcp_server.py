from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.mcp_server import handle_message
from app.ner import reset_recognizer_cache
from app.store import SessionStore


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_engine = os.environ.get("QINGJIAO_NER_ENGINE")
        os.environ["QINGJIAO_NER_ENGINE"] = "demo"
        reset_recognizer_cache()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.tmpdir.name))

    def tearDown(self) -> None:
        self.tmpdir.cleanup()
        if self._old_engine is None:
            os.environ.pop("QINGJIAO_NER_ENGINE", None)
        else:
            os.environ["QINGJIAO_NER_ENGINE"] = self._old_engine
        reset_recognizer_cache()

    def test_initialize_list_redact_and_restore(self) -> None:
        init = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"}, self.store)
        self.assertIsNotNone(init)
        self.assertEqual(init["result"]["serverInfo"]["name"], "qingjiao-redact-community")

        tools = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, self.store)
        names = [t["name"] for t in tools["result"]["tools"]]
        self.assertIn("redact_text", names)
        self.assertIn("restore_text", names)

        redact_res = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "redact_text",
                    "arguments": {"text": "陈清扬负责华东算力联合实验室项目。"},
                },
            },
            self.store,
        )
        payload = json.loads(redact_res["result"]["content"][0]["text"])
        self.assertIn("{{人名_0001}}", payload["redacted_text"])
        self.assertIn("{{机构_0001}}", payload["redacted_text"])

        restore_res = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "restore_text",
                    "arguments": {
                        "session_id": payload["session_id"],
                        "text": "结论：{{人名_0001}} 已完成 {{机构_0001}} 汇报。",
                    },
                },
            },
            self.store,
        )
        restored = json.loads(restore_res["result"]["content"][0]["text"])
        self.assertTrue(restored["ok"])
        self.assertEqual(restored["restored_text"], "结论：陈清扬 已完成 华东算力联合实验室 汇报。")


if __name__ == "__main__":
    unittest.main()
