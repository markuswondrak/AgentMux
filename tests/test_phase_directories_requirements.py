from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.runtime.event_bus import SessionEvent
from agentmux.workflow.handlers import load_plan_meta
from agentmux.workflow.interruptions import InterruptionService
from agentmux.workflow.orchestrator import PipelineOrchestrator
from agentmux.workflow.plan_parser import coder_label_for_subplan, read_subplan_title, split_plan_into_subplans
from agentmux.workflow.prompts import write_prompt_file
from agentmux.sessions.state_store import create_feature_files, load_state
from agentmux.workflow.transitions import EXIT_SUCCESS, PipelineContext


class _FakeEventBus:
    def __init__(self) -> None:
        self.registered = []
        self.start_calls = 0
        self.stop_calls = 0

    def register(self, listener) -> None:
        self.registered.append(listener)

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class _InterruptionOnStartBus(_FakeEventBus):
    def start(self) -> None:
        super().start()
        event = SessionEvent(
            kind="interruption.pane_exited",
            source="interruption",
            payload={"message": "Agent pane coder 2 was closed or exited (for example via Ctrl-C)."},
        )
        for listener in list(self.registered):
            listener(event)


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
            self.assertEqual(feature_dir / "08_completion", files.completion_dir)
            self.assertFalse((feature_dir / "01_product_management").exists())
            self.assertFalse(files.planning_dir.exists())
            self.assertFalse(files.research_dir.exists())
            self.assertFalse(files.design_dir.exists())
            self.assertFalse(files.implementation_dir.exists())
            self.assertFalse(files.review_dir.exists())
            self.assertFalse(files.completion_dir.exists())
            self.assertEqual(feature_dir / "02_planning" / "plan.md", files.plan)
            self.assertEqual(feature_dir / "02_planning" / "tasks.md", files.tasks)
            self.assertEqual(feature_dir / "02_planning" / "execution_plan.json", files.execution_plan)
            self.assertEqual(feature_dir / "04_design" / "design.md", files.design)
            self.assertEqual(feature_dir / "06_review" / "review.md", files.review)
            self.assertEqual(feature_dir / "06_review" / "fix_request.md", files.fix_request)
            self.assertEqual(feature_dir / "08_completion" / "changes.md", files.changes)
            self.assertEqual(
                feature_dir / "01_product_management" / "approved_preferences.json",
                files.pm_preference_proposal,
            )
            self.assertEqual(
                feature_dir / "02_planning" / "approved_preferences.json",
                files.architect_preference_proposal,
            )
            self.assertEqual(
                feature_dir / "08_completion" / "approved_preferences.json",
                files.reviewer_preference_proposal,
            )

    def test_create_feature_files_initializes_staged_execution_state_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")
            state = load_state(files.state)

            self.assertEqual(0, state["implementation_group_total"])
            self.assertEqual(0, state["implementation_group_index"])
            self.assertEqual([], state["implementation_active_plan_ids"])
            self.assertEqual([], state["implementation_completed_group_ids"])
            self.assertIsNone(state["implementation_group_mode"])

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

    def test_read_subplan_title_extracts_header_title(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            subplan_path = Path(td) / "plan_2.md"
            subplan_path.write_text("# Plan\n\n## Sub-plan 2: API wiring\n\nDo it\n", encoding="utf-8")

            self.assertEqual("API wiring", read_subplan_title(subplan_path))

    def test_coder_label_for_subplan_falls_back_when_header_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            planning_dir = Path(td)
            (planning_dir / "plan_4.md").write_text("# Plan\n\nNo subplan header here\n", encoding="utf-8")

            self.assertEqual("plan 4", coder_label_for_subplan(planning_dir, 4))

    def test_orchestrate_starts_and_stops_event_bus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")
            bus = _FakeEventBus()
            orchestrator = PipelineOrchestrator(InterruptionService())
            ctx = PipelineContext(
                files=files,
                runtime=_FakeRuntime(),
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            with patch(
                "agentmux.workflow.orchestrator.PipelineOrchestrator.build_event_bus",
                return_value=bus,
            ) as build_bus_mock, patch(
                "agentmux.workflow.orchestrator.run_phase_cycle",
                return_value=EXIT_SUCCESS,
            ):
                result = orchestrator.run(ctx, keep_session=False)

            self.assertEqual(0, result)
            build_bus_mock.assert_called_once()
            self.assertEqual(1, bus.start_calls)
            self.assertEqual(1, bus.stop_calls)

    def test_orchestrate_cancels_run_when_event_bus_reports_pane_exit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "phase dirs", "session-x")
            bus = _InterruptionOnStartBus()
            orchestrator = PipelineOrchestrator(InterruptionService())
            ctx = PipelineContext(
                files=files,
                runtime=_FakeRuntime(),
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            with patch(
                "agentmux.workflow.orchestrator.PipelineOrchestrator.build_event_bus",
                return_value=bus,
            ), patch("agentmux.workflow.orchestrator.run_phase_cycle") as run_phase_cycle_mock:
                result = orchestrator.run(ctx, keep_session=False)

            self.assertEqual(130, result)
            run_phase_cycle_mock.assert_not_called()
            state = load_state(files.state)
            self.assertEqual("failed", state["phase"])
            self.assertEqual("run_canceled", state["last_event"])
            self.assertEqual("canceled", state["interruption_category"])
            self.assertIn("coder 2", state["interruption_cause"])


if __name__ == "__main__":
    unittest.main()
