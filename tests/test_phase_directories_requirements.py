from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentmux.pipeline as pipeline
from agentmux.handlers import load_plan_meta
from agentmux.plan_parser import split_plan_into_subplans
from agentmux.prompts import write_prompt_file
from agentmux.state import create_feature_files
from agentmux.transitions import EXIT_SUCCESS


class _FakeObserver:
    last_instance: "_FakeObserver | None" = None

    def __init__(self) -> None:
        self.schedule_calls: list[tuple[object, str, bool]] = []
        _FakeObserver.last_instance = self

    def schedule(self, handler, path: str, recursive: bool = False) -> None:
        self.schedule_calls.append((handler, path, recursive))

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def join(self) -> None:
        return None


class _FakeRuntime:
    def shutdown(self, keep_session: bool) -> None:
        _ = keep_session


class PhaseDirectoryRequirementsTests(unittest.TestCase):
    def test_create_feature_files_initializes_phase_subdirectories_and_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")

            self.assertEqual(feature_dir / "planning", files.planning_dir)
            self.assertEqual(feature_dir / "research", files.research_dir)
            self.assertEqual(feature_dir / "design", files.design_dir)
            self.assertEqual(feature_dir / "implementation", files.implementation_dir)
            self.assertEqual(feature_dir / "review", files.review_dir)
            self.assertEqual(feature_dir / "docs", files.docs_dir)
            self.assertEqual(feature_dir / "completion", files.completion_dir)
            self.assertTrue(files.planning_dir.is_dir())
            self.assertTrue(files.research_dir.is_dir())
            self.assertTrue(files.design_dir.is_dir())
            self.assertTrue(files.implementation_dir.is_dir())
            self.assertTrue(files.review_dir.is_dir())
            self.assertTrue(files.docs_dir.is_dir())
            self.assertTrue(files.completion_dir.is_dir())
            self.assertEqual(feature_dir / "planning" / "plan.md", files.plan)
            self.assertEqual(feature_dir / "planning" / "tasks.md", files.tasks)
            self.assertEqual(feature_dir / "design" / "design.md", files.design)
            self.assertEqual(feature_dir / "review" / "review.md", files.review)
            self.assertEqual(feature_dir / "review" / "fix_request.md", files.fix_request)
            self.assertEqual(feature_dir / "completion" / "changes.md", files.changes)

    def test_write_prompt_file_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_path = write_prompt_file(feature_dir, "research/code-auth/prompt.md", "hello")
            self.assertEqual(feature_dir / "research" / "code-auth" / "prompt.md", prompt_path)
            self.assertEqual("hello", prompt_path.read_text(encoding="utf-8"))

    def test_load_plan_meta_reads_from_planning_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / "planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "plan_meta.json").write_text('{"needs_design": true}', encoding="utf-8")

            meta = load_plan_meta(planning_dir)

            self.assertEqual({"needs_design": True}, meta)

    def test_split_plan_into_subplans_writes_into_planning_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / "planning"
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

    def test_orchestrate_watches_feature_directory_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")

            with patch("agentmux.pipeline.Observer", _FakeObserver), patch(
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
            observer = _FakeObserver.last_instance
            self.assertIsNotNone(observer)
            assert observer is not None
            self.assertEqual(1, len(observer.schedule_calls))
            _, path, recursive = observer.schedule_calls[0]
            self.assertEqual(str(feature_dir), path)
            self.assertTrue(recursive)


if __name__ == "__main__":
    unittest.main()
