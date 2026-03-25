from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.mcp_research_server import (
    agentmux_research_await,
    agentmux_research_dispatch_code,
    agentmux_research_dispatch_web,
)


class McpResearchServerRequirementsTests(unittest.TestCase):
    def test_dispatch_code_creates_request_with_expected_sections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                result = agentmux_research_dispatch_code(
                    topic="auth-module",
                    context="Planning auth changes",
                    questions=["Where is auth middleware defined?", "What services call it?"],
                    scope_hints=["agentmux/", "tests/"],
                )

            request_path = feature_dir / "research" / "code-auth-module" / "request.md"
            request = request_path.read_text(encoding="utf-8")
            self.assertEqual("Code research on 'auth-module' dispatched.", result)
            self.assertIn("## Context", request)
            self.assertIn("Planning auth changes", request)
            self.assertIn("## Questions", request)
            self.assertIn("1. Where is auth middleware defined?", request)
            self.assertIn("2. What services call it?", request)
            self.assertIn("## Scope hints", request)
            self.assertIn("- agentmux/", request)
            self.assertIn("- tests/", request)

    def test_dispatch_web_creates_request_and_handles_empty_scope_hints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                result = agentmux_research_dispatch_web(
                    topic="sdk-compat",
                    context="Need latest SDK compatibility matrix",
                    questions=["Which SDK versions support MCP?"],
                    scope_hints=None,
                )

            request_path = feature_dir / "research" / "web-sdk-compat" / "request.md"
            request = request_path.read_text(encoding="utf-8")
            self.assertEqual("Web research on 'sdk-compat' dispatched.", result)
            self.assertIn("## Scope hints", request)
            self.assertIn("- (none provided)", request)

    def test_dispatch_rejects_invalid_topic_slug(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                with self.assertRaises(ValueError):
                    agentmux_research_dispatch_code(
                        topic="Auth_Module",
                        context="x",
                        questions=["q"],
                        scope_hints=None,
                    )

    def test_await_returns_missing_task_message_when_research_dir_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                result = agentmux_research_await("auth-module", "code", timeout=1)

            self.assertIn("No research task found", result)

    def test_await_returns_summary_or_detail_when_done_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            topic_dir = feature_dir / "research" / "code-auth-module"
            topic_dir.mkdir(parents=True)
            (topic_dir / "summary.md").write_text("summary text", encoding="utf-8")
            (topic_dir / "detail.md").write_text("detail text", encoding="utf-8")
            (topic_dir / "done").touch()

            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                summary = agentmux_research_await("auth-module", "code", timeout=1)
                detail = agentmux_research_await("auth-module", "code", detail=True, timeout=1)

            self.assertEqual("summary text", summary)
            self.assertEqual("detail text", detail)

    def test_await_times_out_if_done_marker_never_appears(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            topic_dir = feature_dir / "research" / "web-openai"
            topic_dir.mkdir(parents=True)

            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                result = agentmux_research_await("openai", "web", timeout=1)

            self.assertEqual("Research on 'openai' timed out after 1s.", result)

    def test_await_blocks_until_done_marker_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            topic_dir = feature_dir / "research" / "code-runtime"
            topic_dir.mkdir(parents=True)

            def complete_later() -> None:
                time.sleep(0.2)
                (topic_dir / "summary.md").write_text("runtime summary", encoding="utf-8")
                (topic_dir / "done").touch()

            worker = threading.Thread(target=complete_later, daemon=True)
            worker.start()

            with patch.dict(os.environ, {"FEATURE_DIR": str(feature_dir)}, clear=False):
                started = time.monotonic()
                result = agentmux_research_await("runtime", "code", timeout=3)
                elapsed = time.monotonic() - started

            worker.join(timeout=1)
            self.assertGreaterEqual(elapsed, 0.15)
            self.assertEqual("runtime summary", result)


if __name__ == "__main__":
    unittest.main()
