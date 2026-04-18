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


class McpServerActivesessionFallbackTests(unittest.TestCase):
    """Tests that mcp_server reads FEATURE_DIR and AGENTMUX_ALLOWED_TOOLS from
    .agentmux/.active_session when the env vars are absent (Cursor MCP subprocess
    case)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.project_dir = self.tmp_path / "project"
        self.project_dir.mkdir()
        os.environ.pop("FEATURE_DIR", None)
        os.environ.pop("AGENTMUX_ALLOWED_TOOLS", None)
        os.environ["PROJECT_DIR"] = str(self.project_dir)

    def tearDown(self):
        os.environ.pop("FEATURE_DIR", None)
        os.environ.pop("AGENTMUX_ALLOWED_TOOLS", None)
        os.environ.pop("PROJECT_DIR", None)
        self._tmpdir.cleanup()

    def _write_active_session(self, data: dict) -> None:
        active_path = self.project_dir / ".agentmux" / ".active_session"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text(
            json.dumps(data) + "\n",
            encoding="utf-8",
        )

    def test_feature_dir_falls_back_to_active_session_file(self) -> None:
        """When FEATURE_DIR env is absent, _feature_dir() reads from .active_session."""
        feature_dir = self.project_dir / "sessions" / "my-session"
        feature_dir.mkdir(parents=True)
        self._write_active_session({"feature_dir": str(feature_dir)})

        result = mcp_server._feature_dir()

        self.assertEqual(result, feature_dir.resolve())

    def test_feature_dir_env_var_takes_priority_over_active_session(self) -> None:
        """When FEATURE_DIR env is set, it takes priority over .active_session."""
        env_feature_dir = self.project_dir / "sessions" / "env-session"
        env_feature_dir.mkdir(parents=True)
        stale_feature_dir = self.project_dir / "sessions" / "stale-session"
        stale_feature_dir.mkdir(parents=True)
        self._write_active_session({"feature_dir": str(stale_feature_dir)})
        os.environ["FEATURE_DIR"] = str(env_feature_dir)

        result = mcp_server._feature_dir()

        self.assertEqual(result, env_feature_dir.resolve())

    def test_feature_dir_raises_when_absent_and_no_active_session(self) -> None:
        """RuntimeError if FEATURE_DIR is absent and no .active_session exists."""
        with self.assertRaises(RuntimeError):
            mcp_server._feature_dir()

    def test_allowed_tools_falls_back_to_active_session_file(self) -> None:
        """When AGENTMUX_ALLOWED_TOOLS env is absent, reads from .active_session."""
        self._write_active_session(
            {"feature_dir": "/tmp/x", "allowed_tools": "submit_done,submit_plan"}
        )

        result = mcp_server._get_allowed_tools()

        self.assertEqual(result, frozenset({"submit_done", "submit_plan"}))

    def test_allowed_tools_env_var_takes_priority_over_active_session(self) -> None:
        """AGENTMUX_ALLOWED_TOOLS env takes priority over .active_session."""
        self._write_active_session(
            {"feature_dir": "/tmp/x", "allowed_tools": "submit_plan"}
        )
        os.environ["AGENTMUX_ALLOWED_TOOLS"] = "submit_done"

        result = mcp_server._get_allowed_tools()

        self.assertEqual(result, frozenset({"submit_done"}))

    def test_feature_dir_active_session_fallback_soft_fails_on_corrupt_file(
        self,
    ) -> None:
        """Corrupt .active_session: _feature_dir() raises RuntimeError."""
        active_path = self.project_dir / ".agentmux" / ".active_session"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text("{{not valid json", encoding="utf-8")

        with self.assertRaises(RuntimeError):
            mcp_server._feature_dir()

    def test_allowed_tools_returns_none_when_active_session_has_no_tools_key(
        self,
    ) -> None:
        """If .active_session has no 'allowed_tools', _get_allowed_tools() is None."""
        self._write_active_session({"feature_dir": "/tmp/x"})

        result = mcp_server._get_allowed_tools()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
