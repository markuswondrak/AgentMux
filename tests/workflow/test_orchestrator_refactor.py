"""Tests for the refactored event-driven orchestrator."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.runtime.event_bus import SessionEvent
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PHASE_HANDLERS
from agentmux.workflow.orchestrator import PipelineOrchestrator
from agentmux.workflow.transitions import PipelineContext


class _FakeRuntime:
    """Mock runtime for testing."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self._shutdown_called = False

    def notify(self, role: str, message: str) -> None:
        self.notifications.append((role, message))

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


if __name__ == "__main__":
    unittest.main()
