from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_coder_prompt,
    build_reviewer_prompt,
)
from agentmux.state import create_feature_files, load_runtime_files


class TasksRequirementsTests(unittest.TestCase):
    def test_runtime_files_include_tasks_and_placeholders_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "add tasks list", "session")
            loaded = load_runtime_files(project_dir, feature_dir)

            self.assertEqual(feature_dir / "planning" / "tasks.md", files.tasks)
            self.assertEqual(feature_dir / "planning" / "tasks.md", loaded.tasks)
            self.assertFalse(files.plan.exists())
            self.assertFalse(files.tasks.exists())
            self.assertFalse(files.design.exists())
            self.assertFalse(files.review.exists())
            self.assertFalse(files.fix_request.exists())

    def test_architect_and_coder_prompts_reference_plan_meta_and_done_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "add tasks list", "session")

            architect_prompt = build_architect_prompt(files)
            coder_prompt = build_coder_prompt(files)

            self.assertIn("write the final plan to `planning/plan.md`", architect_prompt)
            self.assertIn("also write `planning/tasks.md`", architect_prompt)
            self.assertIn("write `planning/plan_meta.json`", architect_prompt)
            self.assertIn("implementation/done_1", coder_prompt)
            self.assertIn("Do not update state.json", coder_prompt)

    def test_change_prompt_references_files_instead_of_embedding_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "add tasks list", "session")
            files.changes.write_text("change request", encoding="utf-8")
            files.plan.write_text("# Plan\n\n1. Example step\n", encoding="utf-8")
            files.tasks.write_text("# Tasks\n\n1. Example task\n", encoding="utf-8")

            prompt = build_change_prompt(files)

            self.assertIn("Read these files first:", prompt)
            self.assertIn("- requirements.md", prompt)
            self.assertIn("- planning/plan.md", prompt)
            self.assertIn("- planning/tasks.md", prompt)
            self.assertIn("- completion/changes.md", prompt)
            self.assertIn("planning/plan_meta.json", prompt)
            self.assertNotIn("1. Example task", prompt)

    def test_architect_prompt_no_longer_accepts_review_mode_and_reviewer_prompt_handles_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "review split", "session")

            with self.assertRaises(TypeError):
                build_architect_prompt(files, is_review=True)  # type: ignore[call-arg]

            review_prompt = build_reviewer_prompt(files, is_review=True)
            self.assertIn("reviewer agent in review mode", review_prompt)


if __name__ == "__main__":
    unittest.main()
