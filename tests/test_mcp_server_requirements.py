from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import agentmux.integrations.mcp_server as mcp_server


class _FeatureDirMixin:
    """Mixin providing a temporary feature directory with FEATURE_DIR env."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.feature_dir = Path(self._tmpdir.name)
        os.environ["FEATURE_DIR"] = str(self.feature_dir)

    def tearDown(self):
        os.environ.pop("FEATURE_DIR", None)
        self._tmpdir.cleanup()

    def _read_log_entries(self):
        log_path = self.feature_dir / "tool_events.jsonl"
        if not log_path.exists():
            return []
        return [json.loads(line) for line in log_path.read_text().strip().splitlines()]


class McpServerRequirementsTests(_FeatureDirMixin, unittest.TestCase):
    def test_dispatch_code_appends_to_log_with_expected_payload(self) -> None:
        result = mcp_server.research_dispatch_code(
            topic="auth-module",
            context="Planning auth changes",
            questions=[
                "Where is auth middleware defined?",
                "What services call it?",
            ],
            scope_hints=["agentmux/", "tests/"],
        )

        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "research_dispatch_code")
        payload = entries[0]["payload"]
        self.assertEqual(payload["topic"], "auth-module")
        self.assertEqual(payload["research_type"], "code")
        self.assertEqual(payload["context"], "Planning auth changes")
        self.assertIn("Where is auth middleware defined?", payload["questions"])
        self.assertEqual(payload["scope_hints"], ["agentmux/", "tests/"])
        self.assertEqual("Code research on 'auth-module' dispatched.", result)

    def test_dispatch_web_appends_and_handles_empty_scope_hints(self) -> None:
        result = mcp_server.research_dispatch_web(
            topic="sdk-compat",
            context="Need latest SDK compatibility matrix",
            questions=["Which SDK versions support MCP?"],
            scope_hints=None,
        )

        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["payload"]["research_type"], "web")
        self.assertIsNone(entries[0]["payload"]["scope_hints"])
        self.assertEqual("Web research on 'sdk-compat' dispatched.", result)

    def test_dispatch_code_accepts_scope_hints_as_single_string(self) -> None:
        mcp_server.research_dispatch_code(
            topic="planning-conventions",
            context="Understand planning conventions",
            questions=["Which tests constrain planning artifacts?"],
            scope_hints="Start with prompts and planning tests.",
        )

        entries = self._read_log_entries()
        self.assertEqual(
            entries[0]["payload"]["scope_hints"],
            ["Start with prompts and planning tests."],
        )

    def test_dispatch_code_treats_blank_scope_hints_string_as_none(self) -> None:
        mcp_server.research_dispatch_code(
            topic="feature-surface",
            context="Survey likely feature surfaces",
            questions=["What are the likely extension points?"],
            scope_hints="   ",
        )

        entries = self._read_log_entries()
        self.assertIsNone(entries[0]["payload"]["scope_hints"])

    def test_dispatch_rejects_invalid_topic_slug(self) -> None:
        with self.assertRaises(ValueError):
            mcp_server.research_dispatch_code(
                topic="Auth_Module",
                context="x",
                questions=["q"],
                scope_hints=None,
            )

    def test_module_no_longer_exposes_blocking_await_tool(self) -> None:
        self.assertFalse(hasattr(mcp_server, "agentmux_research_await"))
        self.assertFalse(hasattr(mcp_server, "research_await"))

    def test_dispatch_rejects_missing_feature_dir_env(self) -> None:
        os.environ.pop("FEATURE_DIR", None)
        with self.assertRaises(RuntimeError):
            mcp_server.research_dispatch_code(
                topic="runtime",
                context="Planning runtime changes",
                questions=["Where is runtime created?"],
                scope_hints=None,
            )

    def test_dispatch_does_not_write_request_md(self) -> None:
        mcp_server.research_dispatch_code(
            topic="test-topic",
            context="x",
            questions=["q"],
        )
        for p in self.feature_dir.rglob("request.md"):
            self.fail(f"request.md should not exist: {p}")


if __name__ == "__main__":
    unittest.main()
