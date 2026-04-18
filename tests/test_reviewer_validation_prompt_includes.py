"""Tests for optional validation status includes in reviewer command prompts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files, load_runtime_files
from agentmux.workflow import prompts as prompts_module
from agentmux.workflow.prompts import (
    build_reviewer_followup_prompt,
    build_reviewer_prompt,
)

_VALIDATION_INCLUDE = "[[include-optional:07_review/validation_status.md]]"


class ReviewerValidationStatusIncludeTests(unittest.TestCase):
    def test_review_command_templates_reference_optional_validation_status(
        self,
    ) -> None:
        commands = prompts_module.PROMPTS_DIR / "commands"
        for name in ("review", "review_followup"):
            with self.subTest(template=name):
                text = (commands / f"{name}.md").read_text(encoding="utf-8")
                self.assertIn(_VALIDATION_INCLUDE, text)

    def test_build_reviewer_review_prompt_inlines_validation_status_when_present(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            project_dir = tmp / "project"
            feature_dir = tmp / "feature"
            create_feature_files(
                project_dir, feature_dir, "req", session_name="s", product_manager=False
            )
            rev_dir = feature_dir / "07_review"
            rev_dir.mkdir(parents=True, exist_ok=True)
            (rev_dir / "validation_status.md").write_text(
                "Automated validation: OK\n", encoding="utf-8"
            )

            files = load_runtime_files(project_dir, feature_dir)
            prompt = build_reviewer_prompt(files, is_review=True)

            self.assertIn("Automated validation: OK", prompt)
            self.assertNotIn("[[include-optional:", prompt)

    def test_build_reviewer_review_prompt_omits_validation_when_file_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            project_dir = tmp / "project"
            feature_dir = tmp / "feature"
            create_feature_files(
                project_dir, feature_dir, "req", session_name="s", product_manager=False
            )

            files = load_runtime_files(project_dir, feature_dir)
            prompt = build_reviewer_prompt(files, is_review=True)

            self.assertNotIn("[[include-optional:", prompt)
            self.assertNotIn("Automated validation", prompt)

    def test_followup_prompt_inlines_validation_status_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            project_dir = tmp / "project"
            feature_dir = tmp / "feature"
            create_feature_files(
                project_dir, feature_dir, "req", session_name="s", product_manager=False
            )
            rev_dir = feature_dir / "07_review"
            rev_dir.mkdir(parents=True, exist_ok=True)
            (rev_dir / "fix_request.md").write_text(
                "- fix the thing\n", encoding="utf-8"
            )
            (rev_dir / "validation_status.md").write_text(
                "Lint and tests passed.\n", encoding="utf-8"
            )

            files = load_runtime_files(project_dir, feature_dir)
            prompt = build_reviewer_followup_prompt(
                files,
                pane_role="reviewer_logic",
                fix_request_rel="07_review/fix_request.md",
                review_iteration=2,
            )

            self.assertIn("Lint and tests passed.", prompt)
            self.assertNotIn("[[include-optional:", prompt)


if __name__ == "__main__":
    unittest.main()
