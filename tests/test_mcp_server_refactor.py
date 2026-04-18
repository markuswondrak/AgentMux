"""Tests for refactored MCP research server tools.

Submit tools are completion signals: they read and validate the agent-written
YAML file, append a minimal signal to tool_events.jsonl, and return a
confirmation string. They write NO files other than the log.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import agentmux.integrations.mcp_server as mrs


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


class TestResearchDispatchCode(_FeatureDirMixin, unittest.TestCase):
    """Tests for renamed research_dispatch_code tool."""

    def test_validates_topic_and_appends_to_log(self):
        result = mrs.research_dispatch_code(
            topic="auth-module",
            context="Planning auth changes",
            questions=["Where is auth middleware?"],
            scope_hints=["src/"],
        )
        self.assertEqual("Code research on 'auth-module' dispatched.", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "research_dispatch_code")
        self.assertEqual(entries[0]["payload"]["topic"], "auth-module")
        self.assertEqual(entries[0]["payload"]["research_type"], "code")
        self.assertEqual(entries[0]["payload"]["context"], "Planning auth changes")

    def test_does_not_write_request_md(self):
        mrs.research_dispatch_code(
            topic="test-topic",
            context="x",
            questions=["q"],
        )
        # No request.md should be created anywhere
        for p in self.feature_dir.rglob("request.md"):
            self.fail(f"request.md should not exist: {p}")

    def test_rejects_invalid_topic(self):
        with self.assertRaises(ValueError):
            mrs.research_dispatch_code(
                topic="Bad_Topic",
                context="x",
                questions=["q"],
            )

    def test_rejects_empty_questions(self):
        with self.assertRaises(ValueError):
            mrs.research_dispatch_code(
                topic="valid-topic",
                context="x",
                questions=["", "  "],
            )


class TestResearchDispatchWeb(_FeatureDirMixin, unittest.TestCase):
    """Tests for renamed research_dispatch_web tool."""

    def test_validates_and_appends_with_web_type(self):
        result = mrs.research_dispatch_web(
            topic="sdk-compat",
            context="SDK matrix needed",
            questions=["Which SDKs support MCP?"],
        )
        self.assertEqual("Web research on 'sdk-compat' dispatched.", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "research_dispatch_web")
        self.assertEqual(entries[0]["payload"]["research_type"], "web")

    def test_does_not_write_request_md(self):
        mrs.research_dispatch_web(
            topic="test-topic",
            context="x",
            questions=["q"],
        )
        for p in self.feature_dir.rglob("request.md"):
            self.fail(f"request.md should not exist: {p}")


class TestSubmitArchitecture(_FeatureDirMixin, unittest.TestCase):
    """Tests for submit_architecture signal tool."""

    def _write_md(self, content: str = "# Architecture\n\nSome content.\n") -> Path:
        path = self.feature_dir / "02_architecting" / "architecture.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_reads_file_appends_minimal_signal(self):
        self._write_md()
        result = mrs.submit_architecture()
        self.assertIn("Architecture submitted", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["tool"], "submit_architecture")
        self.assertEqual(entries[0]["payload"], {})

    def test_does_not_write_any_extra_files(self):
        self._write_md()
        mrs.submit_architecture()
        self.assertFalse(
            (self.feature_dir / "02_architecting" / "architecture.yaml").exists()
        )

    def test_raises_when_md_missing(self):
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_architecture()
        self.assertIn("architecture.md", str(ctx.exception))

    def test_raises_when_md_empty(self):
        self._write_md("   \n")
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_architecture()
        self.assertIn("empty", str(ctx.exception))


_VALID_PLAN = {
    "version": 2,
    "plan_overview": "# Plan\n\nSetup core modules.",
    "groups": [
        {
            "group_id": "core",
            "mode": "serial",
            "plans": [{"index": 1, "name": "Setup"}],
        }
    ],
    "subplans": [
        {
            "index": 1,
            "title": "Auth module",
            "scope": "User authentication",
            "owned_files": ["src/auth.py"],
            "dependencies": "None",
            "implementation_approach": "Step by step",
            "acceptance_criteria": "Tests pass",
            "tasks": ["Create module", "Write tests"],
        }
    ],
    "review_strategy": {"severity": "medium", "focus": ["security"]},
    "needs_design": False,
    "needs_docs": True,
    "doc_files": ["docs/api.md"],
}


class TestSubmitPlan(_FeatureDirMixin, unittest.TestCase):
    """Tests for submit_plan signal tool."""

    def _write_yaml(self, data=None):
        import yaml

        path = self.feature_dir / "04_planning" / "plan.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data or _VALID_PLAN))

    def test_reads_file_appends_minimal_signal(self):
        self._write_yaml()
        result = mrs.submit_plan()
        self.assertIn("Plan submitted", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["tool"], "submit_plan")
        self.assertEqual(entries[0]["payload"], {})

    def test_does_not_write_any_extra_files(self):
        self._write_yaml()
        mrs.submit_plan()
        self.assertFalse((self.feature_dir / "04_planning" / "plan.md").exists())
        self.assertFalse(
            (self.feature_dir / "04_planning" / "execution_plan.yaml").exists()
        )

    def test_raises_when_yaml_missing(self):
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_plan()
        self.assertIn("plan.yaml", str(ctx.exception))

    def test_validation_error_on_bad_mode(self):
        bad = dict(_VALID_PLAN)
        bad["groups"] = [
            {"group_id": "g1", "mode": "bad", "plans": [{"index": 1, "name": "x"}]}
        ]
        self._write_yaml(bad)
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_plan()
        self.assertIn("mode", str(ctx.exception))

    def test_validation_error_on_empty_subplans(self):
        bad = dict(_VALID_PLAN)
        bad["subplans"] = []
        self._write_yaml(bad)
        with self.assertRaises(ValueError):
            mrs.submit_plan()


class TestSubmitReview(_FeatureDirMixin, unittest.TestCase):
    """Tests for submit_review signal tool."""

    _VALID_PASS = {"verdict": "pass", "summary": "All checks passed"}

    def _write_yaml(self, data):
        import yaml

        path = self.feature_dir / "07_review" / "review.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data))

    def test_pass_reads_file_appends_minimal_signal(self):
        self._write_yaml(self._VALID_PASS)
        result = mrs.submit_review()
        self.assertIn("verdict: pass", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["tool"], "submit_review")
        self.assertEqual(entries[0]["payload"], {})

    def test_does_not_write_any_extra_files(self):
        self._write_yaml(self._VALID_PASS)
        mrs.submit_review()
        self.assertFalse((self.feature_dir / "07_review" / "review.md").exists())

    def test_raises_when_yaml_missing(self):
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_review()
        self.assertIn("review.yaml", str(ctx.exception))

    def test_fail_with_findings_appends_empty_payload(self):
        self._write_yaml(
            {
                "verdict": "fail",
                "summary": "Issues found",
                "findings": [
                    {
                        "location": "src/x.py:10",
                        "issue": "Missing val",
                        "severity": "high",
                        "recommendation": "Add check",
                    }
                ],
            }
        )
        result = mrs.submit_review()
        self.assertIn("verdict: fail", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["payload"], {})

    def test_role_param_includes_role_in_payload(self):
        """When called with role=..., the tool event payload must include role."""
        import yaml

        role = "reviewer_logic"
        path = self.feature_dir / "07_review" / f"review_{role}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self._VALID_PASS))

        _ = mrs.submit_review(role=role)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["tool"], "submit_review")
        self.assertEqual(entries[0]["payload"], {"role": role})

    def test_invalid_role_raises_value_error(self):
        """An unrecognised role must raise ValueError before reading any YAML."""
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_review(role="reviewer_unknown")
        self.assertIn("Invalid role", str(ctx.exception))
        self.assertIn("reviewer_unknown", str(ctx.exception))

    def test_path_traversal_role_raises_value_error(self):
        """A traversal-style role must be rejected before any path is constructed."""
        with self.assertRaises(ValueError):
            mrs.submit_review(role="../../../../etc/passwd")

    def test_fail_without_findings_raises(self):
        self._write_yaml({"verdict": "fail", "summary": "Bad"})
        with self.assertRaises(ValueError) as ctx:
            mrs.submit_review()
        self.assertIn("findings", str(ctx.exception))

    def test_invalid_verdict_raises(self):
        self._write_yaml({"verdict": "maybe", "summary": "Unsure"})
        with self.assertRaises(ValueError):
            mrs.submit_review()

    def test_optional_approved_preferences_accepted(self):
        data = {
            **self._VALID_PASS,
            "approved_preferences": {
                "source_role": "reviewer",
                "approved": [{"target_role": "coder", "bullet": "- Keep tests"}],
            },
        }
        self._write_yaml(data)
        result = mrs.submit_review()
        self.assertIn("verdict: pass", result)


class TestSubmitDone(_FeatureDirMixin, unittest.TestCase):
    """Tests for new submit_done tool."""

    def test_valid_index_appends_and_returns_confirmation(self):
        result = mrs.submit_done(subplan_index=1)
        self.assertEqual("Sub-plan 1 marked done.", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "submit_done")
        self.assertEqual(entries[0]["payload"]["subplan_index"], 1)

    def test_rejects_index_zero(self):
        with self.assertRaises(ValueError):
            mrs.submit_done(subplan_index=0)

    def test_rejects_negative_index(self):
        with self.assertRaises(ValueError):
            mrs.submit_done(subplan_index=-1)

    def test_rejects_non_integer(self):
        with self.assertRaises(ValueError):
            mrs.submit_done(subplan_index="1")

    def test_accepts_higher_index(self):
        result = mrs.submit_done(subplan_index=5)
        self.assertEqual("Sub-plan 5 marked done.", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["payload"]["subplan_index"], 5)


class TestSubmitResearchDone(_FeatureDirMixin, unittest.TestCase):
    """Tests for new submit_research_done tool."""

    def test_valid_code_type_appends(self):
        result = mrs.submit_research_done(topic="auth-module", type="code")
        self.assertEqual("Research on 'auth-module' (code) marked done.", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "submit_research_done")
        self.assertEqual(entries[0]["payload"]["topic"], "auth-module")
        self.assertEqual(entries[0]["payload"]["type"], "code")

    def test_valid_web_type_appends(self):
        result = mrs.submit_research_done(topic="sdk-compat", type="web")
        self.assertEqual("Research on 'sdk-compat' (web) marked done.", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["payload"]["type"], "web")

    def test_rejects_invalid_topic_slug(self):
        with self.assertRaises(ValueError):
            mrs.submit_research_done(topic="Bad_Topic", type="code")

    def test_rejects_invalid_type(self):
        with self.assertRaises(ValueError):
            mrs.submit_research_done(topic="valid-topic", type="invalid")

    def test_rejects_empty_topic(self):
        with self.assertRaises(ValueError):
            mrs.submit_research_done(topic="", type="code")


class TestSubmitPmDone(_FeatureDirMixin, unittest.TestCase):
    """Tests for new submit_pm_done tool."""

    def test_appends_and_returns_confirmation(self):
        result = mrs.submit_pm_done()
        self.assertEqual("Product management phase done.", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "submit_pm_done")
        self.assertEqual(entries[0]["payload"], {})


class TestNoHandoffArtifactsImport(unittest.TestCase):
    """Verify handoff_artifacts is no longer imported in mcp_server."""

    def test_no_handoff_artifacts_import(self):
        import inspect

        source = inspect.getsource(mrs)
        self.assertNotIn("handoff_artifacts", source)


class TestNoAgentmuxPrefix(unittest.TestCase):
    """Verify no tool name has agentmux_ prefix."""

    def test_no_agentmux_prefix_on_tools(self):
        tool_funcs = [
            name
            for name in dir(mrs)
            if name.startswith(("research_dispatch_", "submit_"))
            and not name.startswith("_")
        ]
        for name in tool_funcs:
            self.assertFalse(
                name.startswith("agentmux_"),
                f"Tool {name} still has agentmux_ prefix",
            )


if __name__ == "__main__":
    unittest.main()
