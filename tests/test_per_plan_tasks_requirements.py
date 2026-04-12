"""Tests for per-plan tasks file support in build_coder_subplan_prompt()."""

import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files
from agentmux.workflow.prompts import build_coder_subplan_prompt


class PerPlanTasksFileTests(unittest.TestCase):
    """Test suite for per-plan tasks file support in coder prompts."""

    def _write_coder_inputs_with_per_plan_tasks(
        self, feature_dir: Path, plan_name: str, plan_index: int, tasks_content: str
    ) -> None:
        """Write plan file and corresponding per-plan tasks file."""
        planning_dir = feature_dir / "04_planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / plan_name).write_text(f"## {plan_name}\n", encoding="utf-8")
        (planning_dir / f"tasks_{plan_index}.md").write_text(
            tasks_content, encoding="utf-8"
        )

    def test_coder_prompt_includes_correct_per_plan_tasks_file(self) -> None:
        """Verify coder prompt includes content from the correct per-plan tasks file."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "per-plan tasks test", "session"
            )
            self._write_coder_inputs_with_per_plan_tasks(
                feature_dir,
                "plan_1.md",
                1,
                "# Tasks for Plan 1\n\n"
                "- [ ] Task 1 for plan 1\n"
                "- [ ] Task 2 for plan 1\n",
            )

            coder_prompt = build_coder_subplan_prompt(
                files, feature_dir / "04_planning" / "plan_1.md", 1
            )

            # Should include the per-plan tasks file path placeholder reference
            self.assertIn("04_planning/tasks_1.md", coder_prompt)
            # Should include the actual tasks content from tasks_1.md
            self.assertIn("Task 1 for plan 1", coder_prompt)
            self.assertIn("Task 2 for plan 1", coder_prompt)

    def test_coder_prompt_includes_only_relevant_per_plan_tasks(self) -> None:
        """Verify coder prompt includes only tasks_N content, not other plans."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "multiple plans test", "session"
            )
            planning_dir = feature_dir / "04_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)

            # Create multiple plans with different task content
            (planning_dir / "plan_1.md").write_text(
                "# Plan 1\nsome content", encoding="utf-8"
            )
            (planning_dir / "tasks_1.md").write_text(
                "# Tasks for Plan 1\nspecific task for plan 1", encoding="utf-8"
            )
            (planning_dir / "plan_2.md").write_text(
                "# Plan 2\nsome content", encoding="utf-8"
            )
            (planning_dir / "tasks_2.md").write_text(
                "# Tasks for Plan 2\nspecific task for plan 2", encoding="utf-8"
            )
            (planning_dir / "plan_3.md").write_text(
                "# Plan 3\nsome content", encoding="utf-8"
            )
            (planning_dir / "tasks_3.md").write_text(
                "# Tasks for Plan 3\nspecific task for plan 3", encoding="utf-8"
            )

            # Get prompt for plan_2 - should only include tasks_2 content
            coder_prompt = build_coder_subplan_prompt(
                files, feature_dir / "04_planning" / "plan_2.md", 2
            )

            # Should reference and include tasks_2.md content only
            self.assertIn("04_planning/tasks_2.md", coder_prompt)
            self.assertIn("specific task for plan 2", coder_prompt)
            # Should NOT include other plans' task content
            self.assertNotIn("specific task for plan 1", coder_prompt)
            self.assertNotIn("specific task for plan 3", coder_prompt)

    def test_missing_per_plan_tasks_raises_clear_error(self) -> None:
        """Verify FileNotFoundError with helpful message when tasks_N doesn't exist."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "missing tasks test", "session"
            )
            planning_dir = feature_dir / "04_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)

            # Only create plan file, NOT the corresponding tasks file
            (planning_dir / "plan_5.md").write_text(
                "# Plan 5\nsome content", encoding="utf-8"
            )

            with self.assertRaises(FileNotFoundError) as context:
                build_coder_subplan_prompt(
                    files, feature_dir / "04_planning" / "plan_5.md", 5
                )

            error_message = str(context.exception)
            # Error message should be actionable and mention the missing file
            self.assertIn("tasks_5.md", error_message)
            self.assertIn("architect", error_message.lower())
            self.assertIn("create", error_message.lower())


if __name__ == "__main__":
    unittest.main()
