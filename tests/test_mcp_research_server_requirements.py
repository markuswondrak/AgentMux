from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import agentmux.mcp_research_server as mcp_research_server
from agentmux.models import SESSION_DIR_NAMES


class McpResearchServerRequirementsTests(unittest.TestCase):
    def test_dispatch_code_creates_request_with_expected_sections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            result = mcp_research_server.agentmux_research_dispatch_code(
                topic="auth-module",
                context="Planning auth changes",
                questions=["Where is auth middleware defined?", "What services call it?"],
                feature_dir=str(feature_dir),
                scope_hints=["agentmux/", "tests/"],
            )

            request_path = feature_dir / SESSION_DIR_NAMES["research"] / "code-auth-module" / "request.md"
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
            result = mcp_research_server.agentmux_research_dispatch_web(
                topic="sdk-compat",
                context="Need latest SDK compatibility matrix",
                questions=["Which SDK versions support MCP?"],
                feature_dir=str(feature_dir),
                scope_hints=None,
            )

            request_path = feature_dir / SESSION_DIR_NAMES["research"] / "web-sdk-compat" / "request.md"
            request = request_path.read_text(encoding="utf-8")
            self.assertEqual("Web research on 'sdk-compat' dispatched.", result)
            self.assertIn("## Scope hints", request)
            self.assertIn("- (none provided)", request)

    def test_dispatch_code_accepts_scope_hints_as_single_string(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            mcp_research_server.agentmux_research_dispatch_code(
                topic="planning-conventions",
                context="Understand planning conventions",
                questions=["Which tests constrain planning artifacts?"],
                feature_dir=str(feature_dir),
                scope_hints="Start with prompts and planning tests.",
            )

            request = (
                feature_dir / SESSION_DIR_NAMES["research"] / "code-planning-conventions" / "request.md"
            ).read_text(encoding="utf-8")
            self.assertIn("- Start with prompts and planning tests.", request)

    def test_dispatch_code_treats_blank_scope_hints_string_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            mcp_research_server.agentmux_research_dispatch_code(
                topic="feature-surface",
                context="Survey likely feature surfaces",
                questions=["What are the likely extension points?"],
                feature_dir=str(feature_dir),
                scope_hints="   ",
            )

            request = (
                feature_dir / SESSION_DIR_NAMES["research"] / "code-feature-surface" / "request.md"
            ).read_text(encoding="utf-8")
            self.assertIn("- (none provided)", request)

    def test_dispatch_rejects_invalid_topic_slug(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with self.assertRaises(ValueError):
                mcp_research_server.agentmux_research_dispatch_code(
                    topic="Auth_Module",
                    context="x",
                    questions=["q"],
                    feature_dir=str(feature_dir),
                    scope_hints=None,
                )

    def test_module_no_longer_exposes_blocking_await_tool(self) -> None:
        self.assertFalse(hasattr(mcp_research_server, "agentmux_research_await"))

    def test_dispatch_rejects_missing_feature_dir(self) -> None:
        with self.assertRaises(RuntimeError):
            mcp_research_server.agentmux_research_dispatch_code(
                topic="runtime",
                context="Planning runtime changes",
                questions=["Where is runtime created?"],
                feature_dir=None,
                scope_hints=None,
            )


if __name__ == "__main__":
    unittest.main()
