from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.runtime.event_bus import SessionEvent
from agentmux.sessions.state_store import create_feature_files, load_state
from agentmux.workflow.interruptions import InterruptionService
from agentmux.workflow.orchestrator import PipelineOrchestrator
from agentmux.workflow.phase_helpers import load_plan_meta
from agentmux.workflow.plan_parser import coder_label_for_subplan
from agentmux.workflow.prompts import write_prompt_file
from agentmux.workflow.transitions import PipelineContext


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
            payload={
                "message": (
                    "Agent pane coder 2 was closed or exited (for example via Ctrl-C)."
                ),
            },
        )
        for listener in list(self.registered):
            listener(event)


class _FakeRuntime:
    def send(
        self,
        role: str,
        prompt_file: Path,
        display_label: str | None = None,
        prefix_command: str | None = None,
    ) -> None:
        _ = (role, prompt_file, display_label, prefix_command)

    def shutdown(self, keep_session: bool) -> None:
        _ = keep_session


class PhaseDirectoryRequirementsTests(unittest.TestCase):
    def test_create_feature_files_sets_numbered_runtime_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "phase dirs", "session-x"
            )

            self.assertEqual(feature_dir / "02_architecting", files.architecting_dir)
            self.assertEqual(feature_dir / "04_planning", files.planning_dir)
            self.assertEqual(feature_dir / "03_research", files.research_dir)
            self.assertEqual(feature_dir / "05_design", files.design_dir)
            self.assertEqual(
                feature_dir / "06_implementation", files.implementation_dir
            )
            self.assertEqual(feature_dir / "07_review", files.review_dir)
            self.assertEqual(feature_dir / "08_completion", files.completion_dir)
            self.assertFalse((feature_dir / "01_product_management").exists())
            self.assertFalse(files.architecting_dir.exists())
            self.assertFalse(files.planning_dir.exists())
            self.assertFalse(files.research_dir.exists())
            self.assertFalse(files.design_dir.exists())
            self.assertFalse(files.implementation_dir.exists())
            self.assertFalse(files.review_dir.exists())
            self.assertFalse(files.completion_dir.exists())
            self.assertEqual(
                feature_dir / "02_architecting" / "architecture.md", files.architecture
            )
            self.assertEqual(feature_dir / "04_planning" / "plan.md", files.plan)
            self.assertEqual(feature_dir / "04_planning" / "tasks.md", files.tasks)
            self.assertEqual(
                feature_dir / "04_planning" / "execution_plan.yaml",
                files.execution_plan,
            )
            self.assertEqual(feature_dir / "05_design" / "design.md", files.design)
            self.assertEqual(feature_dir / "07_review" / "review.md", files.review)
            self.assertEqual(
                feature_dir / "07_review" / "fix_request.md", files.fix_request
            )
            self.assertEqual(
                feature_dir / "08_completion" / "changes.md", files.changes
            )

    def test_create_feature_files_initializes_staged_execution_state_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "phase dirs", "session-x"
            )
            state = load_state(files.state)

            self.assertEqual(0, state["implementation_group_total"])
            self.assertEqual(0, state["implementation_group_index"])
            self.assertEqual([], state["implementation_active_plan_ids"])
            self.assertEqual([], state["implementation_completed_group_ids"])
            self.assertIsNone(state["implementation_group_mode"])

    def test_write_prompt_file_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_path = write_prompt_file(
                feature_dir, "03_research/code-auth/prompt.md", "hello"
            )
            self.assertEqual(
                feature_dir / "03_research" / "code-auth" / "prompt.md", prompt_path
            )
            self.assertEqual("hello", prompt_path.read_text(encoding="utf-8"))

    def test_load_plan_meta_reads_from_planning_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / "04_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            import yaml

            (planning_dir / "execution_plan.yaml").write_text(
                yaml.dump({"needs_design": True}, default_flow_style=False),
                encoding="utf-8",
            )

            meta = load_plan_meta(planning_dir)

            self.assertEqual({"needs_design": True}, meta)

    def test_coder_label_for_subplan_reads_name_from_execution_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / "04_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "plan_1.md").write_text(
                "## Sub-plan 1: API wiring\n", encoding="utf-8"
            )
            import yaml

            (planning_dir / "execution_plan.yaml").write_text(
                yaml.dump(
                    {
                        "groups": [
                            {
                                "group_id": "g1",
                                "mode": "serial",
                                "plans": [{"file": "plan_1.md", "name": "API wiring"}],
                            }
                        ],
                    },
                    default_flow_style=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual("API wiring", coder_label_for_subplan(planning_dir, 1))

    def test_coder_label_for_subplan_falls_back_when_execution_plan_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            planning_dir = Path(td)
            self.assertEqual("plan 4", coder_label_for_subplan(planning_dir, 4))

    def test_orchestrate_starts_and_stops_event_bus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(
                project_dir, feature_dir, "phase dirs", "session-x"
            )
            bus = _FakeEventBus()
            orchestrator = PipelineOrchestrator(InterruptionService())
            ctx = PipelineContext(
                files=files,
                runtime=_FakeRuntime(),
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            with (
                patch(
                    "agentmux.workflow.orchestrator.PipelineOrchestrator.build_event_bus",
                    return_value=bus,
                ) as build_bus_mock,
            ):
                # Start run in a thread and trigger exit
                import threading

                result_container = {}

                def run_orchestrator() -> None:
                    result_container["result"] = orchestrator.run(
                        ctx, keep_session=False
                    )

                thread = threading.Thread(target=run_orchestrator)
                thread.start()
                # Wait for registration then trigger exit
                import time

                time.sleep(0.05)
                # _exit_event is initialized in run(), so it should be set by now
                if orchestrator._exit_event is not None:
                    orchestrator._exit_code = 0
                    orchestrator._exit_event.set()
                thread.join(timeout=2.0)

            self.assertEqual(0, result_container.get("result"))
            build_bus_mock.assert_called_once()
            self.assertEqual(1, bus.start_calls)
            self.assertEqual(1, bus.stop_calls)

    def test_orchestrate_cancels_run_when_event_bus_reports_pane_exit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(
                project_dir, feature_dir, "phase dirs", "session-x"
            )
            bus = _InterruptionOnStartBus()
            orchestrator = PipelineOrchestrator(InterruptionService())
            ctx = PipelineContext(
                files=files,
                runtime=_FakeRuntime(),
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            with (
                patch(
                    "agentmux.workflow.orchestrator.PipelineOrchestrator.build_event_bus",
                    return_value=bus,
                ),
            ):
                result = orchestrator.run(ctx, keep_session=False)

            self.assertEqual(130, result)
            state = load_state(files.state)
            self.assertEqual("failed", state["phase"])
            self.assertEqual("run_canceled", state["last_event"])
            self.assertEqual("canceled", state["interruption_category"])
            self.assertIn("coder 2", state["interruption_cause"])


if __name__ == "__main__":
    unittest.main()
