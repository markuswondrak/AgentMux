"""Tests for MCP submission tools (architecture, plan, review).

Submit tools are completion signals: they check/read agent-written files,
append a minimal signal event to tool_events.jsonl, and return a confirmation
string. They write NO files other than the log.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import yaml


class SubmitToolTestBase(unittest.TestCase):
    """Base class providing a temporary feature directory."""

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

    def _write_yaml(self, rel_path: str, data: dict) -> Path:
        """Write a YAML file into the feature dir."""
        path = self.feature_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, default_flow_style=False), encoding="utf-8"
        )
        return path


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

_VALID_REVIEW_PASS = {
    "verdict": "pass",
    "summary": "All checks passed",
}


class TestSubmitArchitecture(SubmitToolTestBase):
    def _write_md(self, content: str = "# Architecture\n\nSome content.\n") -> Path:
        path = self.feature_dir / "02_architecting" / "architecture.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _submit(self, feature_dir=None):
        from agentmux.integrations.mcp_server import submit_architecture

        return submit_architecture(
            feature_dir=feature_dir or str(self.feature_dir),
        )

    def test_appends_minimal_signal_to_log(self):
        self._write_md()
        result = self._submit()
        self.assertIn("Architecture submitted", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "submit_architecture")
        # Payload should be empty — no data carried
        self.assertEqual(entries[0]["payload"], {})

    def test_does_not_write_files(self):
        self._write_md()
        self._submit()
        # Only architecture.md (which WE wrote) should exist; no YAML generated
        self.assertFalse(
            (self.feature_dir / "02_architecting" / "architecture.yaml").exists()
        )

    def test_raises_when_md_missing(self):
        from agentmux.integrations.mcp_server import submit_architecture

        with self.assertRaises(ValueError) as ctx:
            submit_architecture(feature_dir=str(self.feature_dir))
        self.assertIn("architecture.md", str(ctx.exception))

    def test_raises_when_md_empty(self):
        from agentmux.integrations.mcp_server import submit_architecture

        self._write_md("   \n")
        with self.assertRaises(ValueError) as ctx:
            submit_architecture(feature_dir=str(self.feature_dir))
        self.assertIn("empty", str(ctx.exception))


class TestSubmitPlan(SubmitToolTestBase):
    def _submit(self, feature_dir=None):
        from agentmux.integrations.mcp_server import submit_plan

        return submit_plan(
            feature_dir=feature_dir or str(self.feature_dir),
        )

    def test_appends_minimal_signal_to_log(self):
        self._write_yaml("04_planning/plan.yaml", _VALID_PLAN)
        result = self._submit()
        self.assertIn("Plan submitted", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "submit_plan")
        self.assertEqual(entries[0]["payload"], {})

    def test_does_not_write_files(self):
        self._write_yaml("04_planning/plan.yaml", _VALID_PLAN)
        self._submit()
        self.assertFalse((self.feature_dir / "04_planning" / "plan.md").exists())
        self.assertFalse(
            (self.feature_dir / "04_planning" / "execution_plan.yaml").exists()
        )

    def test_raises_when_yaml_missing(self):
        from agentmux.integrations.mcp_server import submit_plan

        with self.assertRaises(ValueError) as ctx:
            submit_plan(feature_dir=str(self.feature_dir))
        self.assertIn("plan.yaml", str(ctx.exception))

    def test_raises_when_yaml_is_not_a_dict(self):
        from agentmux.integrations.mcp_server import submit_plan

        path = self.feature_dir / "04_planning" / "plan.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            submit_plan(feature_dir=str(self.feature_dir))
        self.assertIn("must be a YAML mapping", str(ctx.exception))

    def test_raises_on_invalid_mode(self):
        from agentmux.integrations.mcp_server import submit_plan

        bad = dict(_VALID_PLAN)
        bad["groups"] = [
            {"group_id": "g1", "mode": "bad", "plans": [{"index": 1, "name": "x"}]}
        ]
        self._write_yaml("04_planning/plan.yaml", bad)
        with self.assertRaises(ValueError) as ctx:
            submit_plan(feature_dir=str(self.feature_dir))
        self.assertIn("mode", str(ctx.exception))

    def test_raises_on_empty_subplans(self):
        from agentmux.integrations.mcp_server import submit_plan

        bad = dict(_VALID_PLAN)
        bad["subplans"] = []
        self._write_yaml("04_planning/plan.yaml", bad)
        with self.assertRaises(ValueError):
            submit_plan(feature_dir=str(self.feature_dir))

    def test_preferences_param_writes_bullets_to_agent_prompt(self):
        import os
        import tempfile as tmpmod

        with tmpmod.TemporaryDirectory() as project_td:
            os.environ["PROJECT_DIR"] = project_td
            try:
                from pathlib import Path as _Path

                self._write_yaml("04_planning/plan.yaml", _VALID_PLAN)
                from agentmux.integrations.mcp_server import submit_plan

                result = submit_plan(
                    feature_dir=str(self.feature_dir),
                    preferences=[
                        {
                            "target_role": "coder",
                            "bullet": "- Validate each task before done",
                        }
                    ],
                )
                self.assertIn("Plan submitted", result)
                coder_prompt = (
                    _Path(project_td) / ".agentmux" / "prompts" / "agents" / "coder.md"
                )
                self.assertTrue(coder_prompt.exists())
                self.assertIn(
                    "- Validate each task before done",
                    coder_prompt.read_text(encoding="utf-8"),
                )
            finally:
                os.environ.pop("PROJECT_DIR", None)


class TestSubmitReview(SubmitToolTestBase):
    def _submit(self, feature_dir=None):
        from agentmux.integrations.mcp_server import submit_review

        return submit_review(
            feature_dir=feature_dir or str(self.feature_dir),
        )

    def test_pass_appends_minimal_signal_to_log(self):
        self._write_yaml("07_review/review.yaml", _VALID_REVIEW_PASS)
        result = self._submit()
        self.assertIn("verdict: pass", result)
        entries = self._read_log_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "submit_review")
        self.assertEqual(entries[0]["payload"], {})

    def test_does_not_write_files(self):
        self._write_yaml("07_review/review.yaml", _VALID_REVIEW_PASS)
        self._submit()
        self.assertFalse((self.feature_dir / "07_review" / "review.md").exists())

    def test_raises_when_yaml_missing(self):
        from agentmux.integrations.mcp_server import submit_review

        with self.assertRaises(ValueError) as ctx:
            submit_review(feature_dir=str(self.feature_dir))
        self.assertIn("review.yaml", str(ctx.exception))

    def test_raises_when_yaml_is_not_a_dict(self):
        from agentmux.integrations.mcp_server import submit_review

        path = self.feature_dir / "07_review" / "review.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            submit_review(feature_dir=str(self.feature_dir))
        self.assertIn("must be a YAML mapping", str(ctx.exception))

    def test_fail_with_findings(self):
        data = {
            "verdict": "fail",
            "summary": "Issues found",
            "findings": [
                {
                    "location": "src/x.py:10",
                    "issue": "Missing validation",
                    "severity": "high",
                    "recommendation": "Add check",
                }
            ],
        }
        self._write_yaml("07_review/review.yaml", data)
        result = self._submit()
        self.assertIn("verdict: fail", result)
        entries = self._read_log_entries()
        self.assertEqual(entries[0]["payload"], {})

    def test_fail_without_findings_raises(self):
        from agentmux.integrations.mcp_server import submit_review

        self._write_yaml("07_review/review.yaml", {"verdict": "fail", "summary": "Bad"})
        with self.assertRaises(ValueError) as ctx:
            submit_review(feature_dir=str(self.feature_dir))
        self.assertIn("findings", str(ctx.exception))

    def test_invalid_verdict_raises(self):
        from agentmux.integrations.mcp_server import submit_review

        self._write_yaml(
            "07_review/review.yaml", {"verdict": "maybe", "summary": "Unsure"}
        )
        with self.assertRaises(ValueError):
            submit_review(feature_dir=str(self.feature_dir))

    def test_accepts_optional_commit_message(self):
        data = {**_VALID_REVIEW_PASS, "commit_message": "feat: add auth"}
        self._write_yaml("07_review/review.yaml", data)
        result = self._submit()
        self.assertIn("verdict: pass", result)

    def test_preferences_param_writes_bullets_to_agent_prompt(self):
        import os
        import tempfile as tmpmod

        with tmpmod.TemporaryDirectory() as project_td:
            os.environ["PROJECT_DIR"] = project_td
            try:
                from pathlib import Path as _Path

                self._write_yaml("07_review/review.yaml", _VALID_REVIEW_PASS)
                from agentmux.integrations.mcp_server import submit_review

                result = submit_review(
                    feature_dir=str(self.feature_dir),
                    preferences=[
                        {"target_role": "coder", "bullet": "- Keep regression tests"}
                    ],
                )
                self.assertIn("verdict: pass", result)
                coder_prompt = (
                    _Path(project_td) / ".agentmux" / "prompts" / "agents" / "coder.md"
                )
                self.assertTrue(coder_prompt.exists())
                self.assertIn(
                    "- Keep regression tests",
                    coder_prompt.read_text(encoding="utf-8"),
                )
            finally:
                os.environ.pop("PROJECT_DIR", None)


if __name__ == "__main__":
    unittest.main()
