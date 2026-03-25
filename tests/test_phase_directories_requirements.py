from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

import agentmux.pipeline as pipeline
from agentmux.handlers import load_plan_meta
from agentmux.plan_parser import split_plan_into_subplans
from agentmux.prompts import write_prompt_file
from agentmux.state import create_feature_files
from agentmux.transitions import EXIT_SUCCESS


class _FakeSessionFileMonitor:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeRuntime:
    def shutdown(self, keep_session: bool) -> None:
        _ = keep_session


class PhaseDirectoryRequirementsTests(unittest.TestCase):
    def test_create_feature_files_sets_numbered_runtime_paths_without_eager_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")

            self.assertEqual(feature_dir / "02_planning", files.planning_dir)
            self.assertEqual(feature_dir / "03_research", files.research_dir)
            self.assertEqual(feature_dir / "04_design", files.design_dir)
            self.assertEqual(feature_dir / "05_implementation", files.implementation_dir)
            self.assertEqual(feature_dir / "06_review", files.review_dir)
            self.assertEqual(feature_dir / "07_docs", files.docs_dir)
            self.assertEqual(feature_dir / "08_completion", files.completion_dir)
            self.assertFalse((feature_dir / "01_product_management").exists())
            self.assertFalse(files.planning_dir.exists())
            self.assertFalse(files.research_dir.exists())
            self.assertFalse(files.design_dir.exists())
            self.assertFalse(files.implementation_dir.exists())
            self.assertFalse(files.review_dir.exists())
            self.assertFalse(files.docs_dir.exists())
            self.assertFalse(files.completion_dir.exists())
            self.assertEqual(feature_dir / "02_planning" / "plan.md", files.plan)
            self.assertEqual(feature_dir / "02_planning" / "tasks.md", files.tasks)
            self.assertEqual(feature_dir / "04_design" / "design.md", files.design)
            self.assertEqual(feature_dir / "06_review" / "review.md", files.review)
            self.assertEqual(feature_dir / "06_review" / "fix_request.md", files.fix_request)
            self.assertEqual(feature_dir / "08_completion" / "changes.md", files.changes)

    def test_write_prompt_file_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_path = write_prompt_file(feature_dir, "03_research/code-auth/prompt.md", "hello")
            self.assertEqual(feature_dir / "03_research" / "code-auth" / "prompt.md", prompt_path)
            self.assertEqual("hello", prompt_path.read_text(encoding="utf-8"))

    def test_load_plan_meta_reads_from_planning_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / "02_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "plan_meta.json").write_text('{"needs_design": true}', encoding="utf-8")

            meta = load_plan_meta(planning_dir)

            self.assertEqual({"needs_design": True}, meta)

    def test_split_plan_into_subplans_writes_into_planning_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / "02_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            plan_path = planning_dir / "plan.md"
            plan_path.write_text(
                "# Plan\n\n## Sub-plan 1: A\n\nDo A\n\n## Sub-plan 2: B\n\nDo B\n",
                encoding="utf-8",
            )

            subplans = split_plan_into_subplans(plan_path, planning_dir)

            self.assertEqual([planning_dir / "plan_1.md", planning_dir / "plan_2.md"], subplans)
            self.assertTrue((planning_dir / "plan_1.md").exists())
            self.assertTrue((planning_dir / "plan_2.md").exists())

    def test_orchestrate_starts_and_stops_session_file_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")
            monitor = _FakeSessionFileMonitor()

            with patch(
                "agentmux.pipeline.start_session_file_monitor",
                return_value=monitor,
            ) as start_monitor_mock, patch(
                "agentmux.pipeline.build_initial_prompts",
                return_value={},
            ), patch(
                "agentmux.pipeline.run_phase_cycle",
                return_value=EXIT_SUCCESS,
            ):
                result = pipeline.orchestrate(
                    files=files,
                    runtime=_FakeRuntime(),
                    agents={},
                    max_review_iterations=3,
                    keep_session=False,
                )

            self.assertEqual(0, result)
            start_monitor_mock.assert_called_once_with(
                files.feature_dir,
                files.created_files_log,
                ANY,
            )
            self.assertEqual(1, monitor.stop_calls)


if __name__ == "__main__":
    unittest.main()
