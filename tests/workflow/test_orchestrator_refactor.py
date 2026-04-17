"""Tests for the refactored event-driven orchestrator."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.runtime.event_bus import SessionEvent
from agentmux.runtime.tool_events import load_tool_event_cursor
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PHASE_HANDLERS
from agentmux.workflow.orchestrator import PipelineOrchestrator
from agentmux.workflow.transitions import PipelineContext


class _FakeRuntime:
    """Mock runtime for testing."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.spawned_tasks: list[tuple[str, str, str]] = []
        self.finished_tasks: list[tuple[str, str]] = []
        self.parallel_panes: dict[str, dict[int | str, str]] = {}
        self._shutdown_called = False

    def notify(self, role: str, message: str) -> None:
        self.notifications.append((role, message))

    def spawn_task(self, role: str, task_id: str, research_dir: Path) -> None:
        self.spawned_tasks.append((role, task_id, research_dir.name))
        self.parallel_panes.setdefault(role, {})[task_id] = f"%{role}-{task_id}"

    def finish_task(self, role: str, task_id: str) -> None:
        self.finished_tasks.append((role, task_id))
        if role in self.parallel_panes and task_id in self.parallel_panes[role]:
            del self.parallel_panes[role][task_id]

    def shutdown(self, keep_session: bool) -> None:
        self._shutdown_called = True


class _MockEventBus:
    """Mock event bus that can trigger events manually."""

    def __init__(self) -> None:
        self.listeners: list[callable] = []
        self.started = False
        self.stopped = False

    def register(self, listener: callable) -> None:
        self.listeners.append(listener)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def trigger(self, event: SessionEvent) -> None:
        """Manually trigger an event on all listeners."""
        for listener in self.listeners:
            listener(event)


class TestEventDrivenOrchestrator(unittest.TestCase):
    """Test the event-driven orchestrator refactor."""

    def test_orchestrator_has_router_and_handlers(self) -> None:
        """Verify orchestrator initializes with router and phase handlers."""
        orchestrator = PipelineOrchestrator()

        # Should have a router with PHASE_HANDLERS
        self.assertIsNotNone(orchestrator._router)
        self.assertEqual(orchestrator._router._phases, PHASE_HANDLERS)

    def test_normalize_event_converts_file_events(self) -> None:
        """Test that SessionEvent is converted to WorkflowEvent correctly."""
        orchestrator = PipelineOrchestrator()

        # Test file.created event
        session_event = SessionEvent(
            kind="file.created",
            source="file",
            payload={"relative_path": "planning/plan.md", "content": "test"},
        )

        wf_event = orchestrator._normalize_event(session_event)

        self.assertEqual(wf_event.kind, "file.created")
        self.assertEqual(wf_event.path, "planning/plan.md")
        self.assertEqual(wf_event.payload["content"], "test")

    def test_normalize_event_converts_interruption_events(self) -> None:
        """Test that interruption events are normalized correctly."""
        orchestrator = PipelineOrchestrator()

        session_event = SessionEvent(
            kind="interruption.pane_exited",
            source="interruption",
            payload={"role": "coder", "message": "Pane closed"},
        )

        wf_event = orchestrator._normalize_event(session_event)

        self.assertEqual(wf_event.kind, "interruption.pane_exited")
        self.assertIsNone(wf_event.path)
        self.assertEqual(wf_event.payload["role"], "coder")

    def test_on_event_routes_to_router(self) -> None:
        """Test that _on_event routes events through the router."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")

            # Set initial state to planning phase
            state = load_state(files.state)
            state["phase"] = "planning"
            write_state(files.state, state)

            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            orchestrator._ctx = ctx

            # Mock the router to capture calls
            with patch.object(orchestrator._router, "handle") as mock_handle:
                mock_handle.return_value = ({}, None)  # No updates, no exit

                # Create and send a file event
                session_event = SessionEvent(
                    kind="file.created",
                    source="file",
                    payload={"relative_path": "planning/plan.md"},
                )

                orchestrator._on_event(session_event)

                # Verify router was called with correct WorkflowEvent
                mock_handle.assert_called_once()
                args = mock_handle.call_args[0]
                wf_event, received_state, received_ctx = args

                self.assertEqual(wf_event.kind, "file.created")
                self.assertEqual(wf_event.path, "planning/plan.md")
                self.assertEqual(received_ctx, ctx)

    def test_on_event_sets_exit_code_and_triggers_exit(self) -> None:
        """Test that handler returning exit code triggers shutdown."""
        orchestrator = PipelineOrchestrator()
        orchestrator._exit_event = threading.Event()

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")
            state = load_state(files.state)
            state["phase"] = "planning"
            write_state(files.state, state)

            ctx = PipelineContext(
                files=files,
                runtime=_FakeRuntime(),
                agents={},
                max_review_iterations=3,
                prompts={},
            )
            orchestrator._ctx = ctx

            # Mock router to return exit code 0
            with patch.object(orchestrator._router, "handle") as mock_handle:
                mock_handle.return_value = ({"__exit__": 0}, 0)

                session_event = SessionEvent(
                    kind="file.created",
                    source="file",
                    payload={"relative_path": "test.md"},
                )

                orchestrator._on_event(session_event)

                self.assertEqual(orchestrator._exit_code, 0)
                self.assertTrue(orchestrator._exit_event.is_set())

    def test_on_event_acknowledges_tool_event_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")
            state = load_state(files.state)
            state["phase"] = "planning"
            write_state(files.state, state)

            ctx = PipelineContext(
                files=files,
                runtime=_FakeRuntime(),
                agents={},
                max_review_iterations=3,
                prompts={},
            )
            orchestrator = PipelineOrchestrator()
            orchestrator._ctx = ctx

            with patch.object(orchestrator._router, "handle", return_value=({}, None)):
                session_event = SessionEvent(
                    kind="tool.submit_plan",
                    source="tool_call",
                    payload={
                        "tool": "submit_plan",
                        "payload": {},
                        "_tool_event_meta": {"start_offset": 0, "end_offset": 123},
                    },
                )
                orchestrator._on_event(session_event)

            self.assertEqual(123, load_tool_event_cursor(feature_dir))

    def test_handle_interruption_for_researcher_task(self) -> None:
        """Test that researcher task failures notify the owner."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")

            # Set state to planning phase
            state = load_state(files.state)
            state["phase"] = "planning"
            write_state(files.state, state)

            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )
            orchestrator._ctx = ctx
            orchestrator._exit_event = threading.Event()

            # Create interruption event for code-researcher
            wf_event = WorkflowEvent(
                kind="interruption.pane_exited",
                payload={
                    "role": "code-researcher",
                    "task_id": "auth-analysis",
                    "pane_scope": "parallel",
                    "message": "Process crashed",
                },
            )

            orchestrator._handle_interruption(wf_event, ctx)

            # Should notify architect (owner during planning phase)
            self.assertEqual(len(runtime.notifications), 1)
            role, message = runtime.notifications[0]
            self.assertEqual(role, "architect")
            self.assertIn("RESEARCH TASK FAILED", message)
            self.assertIn("auth-analysis", message)

            # Should set exit code 130
            self.assertEqual(orchestrator._exit_code, 130)
            self.assertTrue(orchestrator._exit_event.is_set())

    def test_handle_interruption_researcher_graceful_exit_with_summary(self) -> None:
        """Researcher exits after producing summary.md -> no cancel, treated as done."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")

            state = load_state(files.state)
            state["phase"] = "product_management"
            state["research_tasks"] = {"auth": "dispatched"}
            write_state(files.state, state)

            # Create summary.md to simulate successful researcher completion
            research_dir = files.research_dir / "code-auth"
            research_dir.mkdir(parents=True)
            (research_dir / "summary.md").write_text(
                "## Auth findings\n", encoding="utf-8"
            )

            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )
            orchestrator._ctx = ctx
            orchestrator._exit_event = threading.Event()

            wf_event = WorkflowEvent(
                kind="interruption.pane_exited",
                payload={
                    "role": "code-researcher",
                    "task_id": "auth",
                    "pane_scope": "parallel",
                    "message": "Process exited normally",
                },
            )

            orchestrator._handle_interruption(wf_event, ctx)

            # Must NOT cancel the session
            self.assertIsNone(orchestrator._exit_code)
            self.assertFalse(orchestrator._exit_event.is_set())

            # Must finish the task and notify the owner
            self.assertIn(("code-researcher", "auth"), runtime.finished_tasks)
            self.assertEqual(1, len(runtime.notifications))
            notify_role, _ = runtime.notifications[0]
            self.assertEqual("product-manager", notify_role)

            # State must mark the task as done
            updated_state = load_state(files.state)
            self.assertEqual("done", updated_state["research_tasks"]["auth"])

    def test_handle_interruption_researcher_crash_without_summary(self) -> None:
        """Researcher exits without producing summary.md -> session canceled."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")

            state = load_state(files.state)
            state["phase"] = "product_management"
            state["research_tasks"] = {"auth": "dispatched"}
            write_state(files.state, state)

            # No summary.md — researcher crashed before finishing
            research_dir = files.research_dir / "code-auth"
            research_dir.mkdir(parents=True)

            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )
            orchestrator._ctx = ctx
            orchestrator._exit_event = threading.Event()

            wf_event = WorkflowEvent(
                kind="interruption.pane_exited",
                payload={
                    "role": "code-researcher",
                    "task_id": "auth",
                    "pane_scope": "parallel",
                    "message": "Process crashed",
                },
            )

            orchestrator._handle_interruption(wf_event, ctx)

            # Must cancel the session
            self.assertEqual(130, orchestrator._exit_code)
            self.assertTrue(orchestrator._exit_event.is_set())

            # Must notify owner about crash
            self.assertEqual(1, len(runtime.notifications))
            notify_role, message = runtime.notifications[0]
            self.assertEqual("product-manager", notify_role)
            self.assertIn("RESEARCH TASK FAILED", message)

    def test_determine_research_owner_product_management(self) -> None:
        """Test owner determination during product_management phase."""
        orchestrator = PipelineOrchestrator()

        state = {"phase": "product_management"}
        owner = orchestrator._determine_research_owner(state, "code-researcher")

        self.assertEqual(owner, "product-manager")

    def test_determine_research_owner_planning(self) -> None:
        """Test owner determination during planning phase."""
        orchestrator = PipelineOrchestrator()

        state = {"phase": "planning"}
        owner = orchestrator._determine_research_owner(state, "code-researcher")

        self.assertEqual(owner, "architect")

    def test_determine_research_owner_implementing(self) -> None:
        """Test owner determination during implementing phase."""
        orchestrator = PipelineOrchestrator()

        state = {"phase": "implementing"}
        owner = orchestrator._determine_research_owner(state, "web-researcher")

        self.assertEqual(owner, "architect")

    def test_determine_research_owner_unknown_phase(self) -> None:
        """Test owner determination for unknown phase returns None."""
        orchestrator = PipelineOrchestrator()

        state = {"phase": "unknown_phase"}
        owner = orchestrator._determine_research_owner(state, "code-researcher")

        self.assertIsNone(owner)

    def test_run_registers_callback_and_blocks(self) -> None:
        """Test that run() registers _on_event and blocks on _exit_event."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")
            state = load_state(files.state)
            state["phase"] = "planning"
            write_state(files.state, state)

            bus = _MockEventBus()
            runtime = _FakeRuntime()

            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            with (
                patch.object(orchestrator, "build_event_bus", return_value=bus),
                patch.object(
                    orchestrator._router, "enter_current_phase", return_value={}
                ),
            ):
                # Start run in a thread so we can trigger events
                result_container = {}

                def run_orchestrator() -> None:
                    result_container["result"] = orchestrator.run(
                        ctx, keep_session=False
                    )

                thread = threading.Thread(target=run_orchestrator)
                thread.start()

                # Wait a bit for registration
                time.sleep(0.1)

                # Verify callback was registered
                self.assertIn(orchestrator._on_event, bus.listeners)
                self.assertTrue(bus.started)

                # Trigger an exit event
                orchestrator._exit_code = 0
                orchestrator._exit_event.set()

                thread.join(timeout=2.0)

                self.assertEqual(result_container.get("result"), 0)
                self.assertTrue(bus.stopped)

    def test_run_bootstraps_phase_before_event_sources_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")
            state = load_state(files.state)
            state["phase"] = "planning"
            write_state(files.state, state)

            bus = _MockEventBus()
            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )
            order: list[str] = []

            def fake_enter(_state, _ctx) -> dict:
                order.append("enter")
                return {}

            def fake_start() -> None:
                order.append("start")
                bus.started = True
                orchestrator._exit_code = 0
                assert orchestrator._exit_event is not None
                orchestrator._exit_event.set()

            bus.start = fake_start

            with (
                patch.object(orchestrator, "build_event_bus", return_value=bus),
                patch.object(
                    orchestrator._router,
                    "enter_current_phase",
                    side_effect=fake_enter,
                ),
            ):
                result = orchestrator.run(ctx, keep_session=False)

            self.assertEqual(0, result)
            self.assertEqual(["enter", "start"], order)

    def test_run_rehydrates_dispatched_research_tasks_after_bus_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "test", "session-x")
            state = load_state(files.state)
            state["phase"] = "planning"
            state["research_tasks"] = {"auth": "dispatched"}
            write_state(files.state, state)

            research_dir = files.research_dir / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")

            bus = _MockEventBus()
            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator()
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
            )

            def fake_start() -> None:
                bus.started = True
                assert orchestrator._exit_event is not None
                orchestrator._exit_event.set()

            bus.start = fake_start

            with (
                patch.object(orchestrator, "build_event_bus", return_value=bus),
                patch.object(
                    orchestrator._router, "enter_current_phase", return_value={}
                ),
            ):
                result = orchestrator.run(ctx, keep_session=False)

            self.assertEqual(0, result)
            self.assertEqual(
                [("code-researcher", "auth", "code-auth")], runtime.spawned_tasks
            )

    def test_no_polling_loop_in_run(self) -> None:
        """Verify the run method does not contain a while True polling loop."""
        import inspect

        source = inspect.getsource(PipelineOrchestrator.run)

        # Should not contain 'while True'
        self.assertNotIn("while True:", source)
        # Should not contain 'wake_event.wait(timeout' (polling pattern)
        self.assertNotIn("wake_event.wait(timeout", source)
        # Should contain '_exit_event.wait()' (blocking pattern)
        self.assertIn("_exit_event.wait()", source)


class RehydrateResearchTasksTests(unittest.TestCase):
    """Tests for _rehydrate_dispatched_research_tasks double-dispatch safeguards."""

    def _make_context(self, files, runtime, state: dict) -> PipelineContext:
        write_state(files.state, state)
        return PipelineContext(
            files=files,
            runtime=runtime,
            agents={},
            max_review_iterations=3,
            prompts={},
        )

    def test_rehydrate_skips_completed_tasks(self) -> None:
        """Task with existing output.log is not re-dispatched."""
        orchestrator = PipelineOrchestrator()
        runtime = _FakeRuntime()
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            research_dir = fdir / "03_research" / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")
            (research_dir / "output.log").write_text("already ran", encoding="utf-8")

            files = type(
                "FakeFiles",
                (),
                {
                    "state": fdir / "state.json",
                    "research_dir": fdir / "03_research",
                    "feature_dir": fdir,
                },
            )()
            write_state(
                files.state,
                {
                    "phase": "architecting",
                    "research_tasks": {"auth": "dispatched"},
                },
            )

            ctx = self._make_context(
                files,
                runtime,
                {
                    "phase": "architecting",
                    "research_tasks": {"auth": "dispatched"},
                },
            )

            orchestrator._rehydrate_dispatched_research_tasks(ctx)

            # Should NOT have spawned — output.log exists
            self.assertEqual([], runtime.spawned_tasks)

    def test_rehydrate_marks_done_if_output_exists(self) -> None:
        """Task with output.log is marked 'done' in state."""
        orchestrator = PipelineOrchestrator()
        runtime = _FakeRuntime()
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            research_dir = fdir / "03_research" / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")
            (research_dir / "summary.md").write_text("done", encoding="utf-8")

            files = type(
                "FakeFiles",
                (),
                {
                    "state": fdir / "state.json",
                    "research_dir": fdir / "03_research",
                    "feature_dir": fdir,
                },
            )()
            ctx = self._make_context(
                files,
                runtime,
                {
                    "phase": "architecting",
                    "research_tasks": {"auth": "dispatched"},
                },
            )

            orchestrator._rehydrate_dispatched_research_tasks(ctx)

            state = load_state(files.state)
            self.assertEqual("done", state["research_tasks"]["auth"])
            self.assertEqual([], runtime.spawned_tasks)

    def test_rehydrate_skips_running_process(self) -> None:
        """Task with alive PID is not re-dispatched."""
        orchestrator = PipelineOrchestrator()
        runtime = _FakeRuntime()
        # Use current process PID as "alive" PID
        import os

        runtime._process_pids = {"auth": os.getpid()}

        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            research_dir = fdir / "03_research" / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")

            files = type(
                "FakeFiles",
                (),
                {
                    "state": fdir / "state.json",
                    "research_dir": fdir / "03_research",
                    "feature_dir": fdir,
                },
            )()
            ctx = self._make_context(
                files,
                runtime,
                {
                    "phase": "architecting",
                    "research_tasks": {"auth": "dispatched"},
                },
            )

            orchestrator._rehydrate_dispatched_research_tasks(ctx)

            self.assertEqual([], runtime.spawned_tasks)

    def test_rehydrate_dispatches_missing_task(self) -> None:
        """Task with prompt.md but no output and no alive PID IS dispatched."""
        orchestrator = PipelineOrchestrator()
        runtime = _FakeRuntime()
        runtime._process_pids = {}  # No alive PIDs

        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            research_dir = fdir / "03_research" / "code-new-topic"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")

            files = type(
                "FakeFiles",
                (),
                {
                    "state": fdir / "state.json",
                    "research_dir": fdir / "03_research",
                    "feature_dir": fdir,
                },
            )()
            ctx = self._make_context(
                files,
                runtime,
                {
                    "phase": "architecting",
                    "research_tasks": {"new-topic": "dispatched"},
                },
            )

            orchestrator._rehydrate_dispatched_research_tasks(ctx)

            self.assertEqual(
                [("code-researcher", "new-topic", "code-new-topic")],
                runtime.spawned_tasks,
            )

    def test_rehydrate_respects_parallel_panes(self) -> None:
        """Task already in parallel_panes is not re-dispatched."""
        orchestrator = PipelineOrchestrator()
        runtime = _FakeRuntime()
        runtime.parallel_panes = {"code-researcher": {"auth": "%code-auth"}}

        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            research_dir = fdir / "03_research" / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")

            files = type(
                "FakeFiles",
                (),
                {
                    "state": fdir / "state.json",
                    "research_dir": fdir / "03_research",
                    "feature_dir": fdir,
                },
            )()
            ctx = self._make_context(
                files,
                runtime,
                {
                    "phase": "architecting",
                    "research_tasks": {"auth": "dispatched"},
                },
            )

            orchestrator._rehydrate_dispatched_research_tasks(ctx)

            self.assertEqual([], runtime.spawned_tasks)

    def test_rehydrate_ignores_non_dispatched_status(self) -> None:
        """Tasks with status != 'dispatched' are ignored."""
        orchestrator = PipelineOrchestrator()
        runtime = _FakeRuntime()

        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            research_dir = fdir / "03_research" / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "prompt.md").write_text("# prompt", encoding="utf-8")

            files = type(
                "FakeFiles",
                (),
                {
                    "state": fdir / "state.json",
                    "research_dir": fdir / "03_research",
                    "feature_dir": fdir,
                },
            )()
            ctx = self._make_context(
                files,
                runtime,
                {
                    "phase": "architecting",
                    "research_tasks": {"auth": "done", "other": "pending"},
                },
            )

            orchestrator._rehydrate_dispatched_research_tasks(ctx)

            self.assertEqual([], runtime.spawned_tasks)

    def test_process_alive_true_for_current_pid(self) -> None:
        """_process_alive returns True for the current process."""
        import os

        self.assertTrue(PipelineOrchestrator._process_alive(os.getpid()))

    def test_process_alive_false_for_dead_pid(self) -> None:
        """_process_alive returns False for a non-existent PID."""
        # PID 1 is usually init, use a very high unlikely PID instead
        self.assertFalse(PipelineOrchestrator._process_alive(999999999))


if __name__ == "__main__":
    unittest.main()
