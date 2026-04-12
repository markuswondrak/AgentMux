"""Tests for the event-driven workflow router infrastructure."""

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentmux.shared.models import (
    AgentConfig,
    GitHubConfig,
    RuntimeFiles,
    WorkflowSettings,
)
from agentmux.workflow.event_router import (
    EventSpec,
    PhaseHandler,
    WorkflowEvent,
    WorkflowEventRouter,
    extract_research_topic,
    extract_subplan_index,
    path_matches,
    path_matches_any,
)
from agentmux.workflow.transitions import PipelineContext


class TestWorkflowEvent:
    """Test WorkflowEvent dataclass creation and attributes."""

    def test_create_file_created_event(self):
        """Verify file.created event with path and payload."""
        event = WorkflowEvent(
            kind="file.created", path="planning/plan.md", payload={"size": 1024}
        )
        assert event.kind == "file.created"
        assert event.path == "planning/plan.md"
        assert event.payload == {"size": 1024}

    def test_create_file_activity_event(self):
        """Verify file.activity event."""
        event = WorkflowEvent(kind="file.activity", path="implementation/done_1")
        assert event.kind == "file.activity"
        assert event.path == "implementation/done_1"
        assert event.payload == {}

    def test_create_interruption_event(self):
        """Verify interruption event with None path."""
        event = WorkflowEvent(
            kind="interruption.pane_exited",
            path=None,
            payload={"pane_id": "coder.0", "exit_code": 0},
        )
        assert event.kind == "interruption.pane_exited"
        assert event.path is None
        assert event.payload == {"pane_id": "coder.0", "exit_code": 0}

    def test_event_is_frozen(self):
        """Verify WorkflowEvent is immutable."""
        event = WorkflowEvent(kind="file.created", path="test.md")
        with pytest.raises(AttributeError):
            event.kind = "file.activity"

    def test_event_equality(self):
        """Verify events can be compared for equality."""
        event1 = WorkflowEvent(kind="file.created", path="test.md")
        event2 = WorkflowEvent(kind="file.created", path="test.md")
        event3 = WorkflowEvent(kind="file.activity", path="test.md")
        assert event1 == event2
        assert event1 != event3


@dataclass
class MockHandler:
    """Mock implementation of PhaseHandler protocol for testing."""

    enter_updates: dict = field(default_factory=dict)
    event_updates: dict = field(default_factory=dict)
    next_phase: str | None = None
    enter_calls: list = field(default_factory=list)
    handle_calls: list = field(default_factory=list)

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Record enter call and return configured updates."""
        self.enter_calls.append((state.copy(), ctx))
        return self.enter_updates

    def get_event_specs(self):
        """Return empty specs — use legacy raw-event path for these tests."""
        return ()

    def get_tool_specs(self):
        """Return empty tool specs — tool events return empty for these tests."""
        return ()

    def handle_event(
        self, event: WorkflowEvent, state: dict, ctx: PipelineContext
    ) -> tuple[dict, str | None]:
        """Record handle call and return configured updates."""
        self.handle_calls.append((event, state.copy(), ctx))
        return self.event_updates, self.next_phase


class TestPhaseHandlerProtocol:
    """Test PhaseHandler protocol compliance."""

    def test_mock_handler_is_instance_of_protocol(self):
        """Verify mock handler satisfies PhaseHandler protocol."""
        handler = MockHandler()
        assert isinstance(handler, PhaseHandler)

    def test_protocol_requires_enter_method(self):
        """Verify objects without enter method don't satisfy protocol."""

        class BadHandler:
            def handle_event(self, event, state, ctx):
                pass

        handler = BadHandler()
        assert not isinstance(handler, PhaseHandler)

    def test_protocol_requires_handle_event_method(self):
        """Verify objects without handle_event don't satisfy protocol."""

        class BadHandler:
            def enter(self, state, ctx):
                pass

        handler = BadHandler()
        assert not isinstance(handler, PhaseHandler)


@pytest.fixture
def mock_context():
    """Create a mock PipelineContext for testing."""
    files = MagicMock(spec=RuntimeFiles)
    files.state = Path("/tmp/test/state.json")
    runtime = MagicMock()
    agents = {"coder": MagicMock(spec=AgentConfig)}
    return PipelineContext(
        files=files,
        runtime=runtime,
        agents=agents,
        max_review_iterations=3,
        prompts={},
        github_config=GitHubConfig(),
        workflow_settings=WorkflowSettings(),
    )


@pytest.fixture
def router():
    """Create a router with mock handlers for all phases."""
    phases = {
        "planning": MockHandler(enter_updates={"subplan_count": 3}),
        "implementing": MockHandler(),
        "reviewing": MockHandler(),
    }
    return WorkflowEventRouter(phases)


class TestWorkflowEventRouter:
    """Test WorkflowEventRouter core functionality."""

    def test_handle_unknown_phase(self, router, mock_context):
        """Verify unknown phase returns empty updates."""
        state = {"phase": "unknown_phase"}
        event = WorkflowEvent(kind="file.created", path="test.md")

        updates, exit_code = router.handle(event, state, mock_context)

        assert updates == {}
        assert exit_code is None

    def test_handle_calls_enter_once_per_phase(self, router, mock_context):
        """Verify enter is called once when first entering a phase."""
        state = {"phase": "planning"}
        event = WorkflowEvent(kind="file.created", path="planning/plan.md")

        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, mock_context)

        handler = router._phases["planning"]
        assert len(handler.enter_calls) == 1
        # State passed to enter() is the original state before updates
        assert handler.enter_calls[0][0] == {"phase": "planning"}

    def test_handle_applies_enter_updates(self, router, mock_context):
        """Verify enter updates are applied to state."""
        state = {"phase": "planning"}
        event = WorkflowEvent(kind="file.created", path="planning/plan.md")

        with patch("agentmux.sessions.state_store.write_state") as mock_write:
            router.handle(event, state, mock_context)

        assert state["subplan_count"] == 3
        mock_write.assert_called()

    def test_handle_calls_handle_event(self, router, mock_context):
        """Verify handle_event is called with correct arguments."""
        state = {"phase": "planning"}
        event = WorkflowEvent(kind="file.created", path="planning/plan.md")

        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, mock_context)

        handler = router._phases["planning"]
        assert len(handler.handle_calls) == 1
        assert handler.handle_calls[0][0] == event

    def test_handle_applies_event_updates(self, router, mock_context):
        """Verify event updates are applied to state."""
        handler = MockHandler(event_updates={"review_iteration": 1})
        phases = {"reviewing": handler}
        router = WorkflowEventRouter(phases)

        state = {"phase": "reviewing"}
        event = WorkflowEvent(kind="file.created", path="review/review.md")

        with patch("agentmux.sessions.state_store.write_state") as mock_write:
            router.handle(event, state, mock_context)

        assert state["review_iteration"] == 1
        mock_write.assert_called()

    def test_handle_phase_transition(self, router, mock_context):
        """Verify phase transition updates state and calls new phase enter."""
        planning_handler = MockHandler(
            enter_updates={"subplan_count": 2}, next_phase="implementing"
        )
        implementing_handler = MockHandler(enter_updates={"started": True})

        phases = {
            "planning": planning_handler,
            "implementing": implementing_handler,
        }
        router = WorkflowEventRouter(phases)

        state = {"phase": "planning"}
        event = WorkflowEvent(kind="file.created", path="planning/plan.md")

        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, mock_context)

        # Should have transitioned to implementing
        assert state["phase"] == "implementing"
        assert state["started"] is True
        # Both enters should have been called
        assert len(planning_handler.enter_calls) == 1
        assert len(implementing_handler.enter_calls) == 1

    def test_handle_exit_success(self, router, mock_context):
        """Verify __exit__: 0 returns success exit code."""
        handler = MockHandler(event_updates={"__exit__": 0})
        phases = {"completing": handler}
        router = WorkflowEventRouter(phases)

        state = {"phase": "completing"}
        event = WorkflowEvent(kind="file.created", path="completion/done")

        with patch("agentmux.sessions.state_store.write_state"):
            updates, exit_code = router.handle(event, state, mock_context)

        assert exit_code == 0
        assert "__exit__" not in updates

    def test_handle_exit_failure(self, router, mock_context):
        """Verify __exit__: 1 returns failure exit code."""
        handler = MockHandler(event_updates={"__exit__": 1})
        phases = {"failed": handler}
        router = WorkflowEventRouter(phases)

        state = {"phase": "failed"}
        event = WorkflowEvent(kind="file.created", path="output.log")

        with patch("agentmux.sessions.state_store.write_state"):
            updates, exit_code = router.handle(event, state, mock_context)

        assert exit_code == 1
        assert "__exit__" not in updates

    def test_enter_not_called_twice_for_same_phase(self, router, mock_context):
        """Verify enter is only called once per phase."""
        handler = MockHandler()
        phases = {"planning": handler}
        router = WorkflowEventRouter(phases)

        state = {"phase": "planning"}
        event1 = WorkflowEvent(kind="file.created", path="planning/plan.md")
        event2 = WorkflowEvent(kind="file.activity", path="planning/tasks.md")

        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event1, state, mock_context)
            router.handle(event2, state, mock_context)

        assert len(handler.enter_calls) == 1  # Only once
        assert len(handler.handle_calls) == 2  # Both events handled

    def test_enter_called_again_after_phase_transition(self, router, mock_context):
        """Verify enter is called again when re-entering a phase."""
        handler = MockHandler(next_phase="planning")  # Loops back
        phases = {"planning": handler}
        router = WorkflowEventRouter(phases)

        state = {"phase": "planning"}
        event = WorkflowEvent(kind="file.created", path="planning/plan.md")

        # Limit recursion for this test
        handler.event_updates = {}  # Clear exit signal after first call
        original_next = handler.next_phase

        call_count = [0]

        def conditional_next(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                return ({}, None)
            return ({}, original_next)

        handler.handle_event = conditional_next

        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, mock_context)

        # Should have entered twice due to loop
        assert len(handler.enter_calls) == 2


class TestPathMatching:
    """Test path matching helper functions."""

    def test_path_matches_exact(self):
        """Verify exact path matching."""
        assert path_matches("planning/plan.md", "planning/plan.md") is True

    def test_path_matches_wildcard(self):
        """Verify wildcard pattern matching."""
        assert (
            path_matches("research/code-*/request.md", "research/code-auth/request.md")
            is True
        )
        assert (
            path_matches("research/code-*/request.md", "research/code-api/request.md")
            is True
        )

    def test_path_matches_no_match(self):
        """Verify non-matching paths return False."""
        assert path_matches("planning/plan.md", "review/review.md") is False
        assert (
            path_matches("research/code-*/request.md", "research/web-auth/request.md")
            is False
        )

    def test_path_matches_done_marker(self):
        """Verify done marker pattern matching."""
        assert path_matches("implementation/done_*", "implementation/done_5") is True
        assert path_matches("implementation/done_*", "implementation/done_1") is True

    def test_path_matches_any_single_match(self):
        """Verify path_matches_any with single matching pattern."""
        patterns = ["planning/plan.md", "review/review.md"]
        assert path_matches_any(patterns, "planning/plan.md") is True

    def test_path_matches_any_multiple_patterns(self):
        """Verify path_matches_any with multiple patterns."""
        patterns = ["planning/*.md", "review/*.md"]
        assert path_matches_any(patterns, "review/review.md") is True
        assert path_matches_any(patterns, "implementation/done_1") is False

    def test_path_matches_any_empty_patterns(self):
        """Verify path_matches_any with empty pattern list."""
        assert path_matches_any([], "planning/plan.md") is False


class TestExtractResearchTopic:
    """Test extract_research_topic helper."""

    def test_extract_code_topic(self):
        """Verify code research topic extraction."""
        result = extract_research_topic("03_research/code-auth/request.md", "code-")
        assert result == "auth"

    def test_extract_web_topic(self):
        """Verify web research topic extraction."""
        result = extract_research_topic("03_research/web-api/result.md", "web-")
        assert result == "api"

    def test_extract_no_match(self):
        """Verify None returned for non-matching paths."""
        result = extract_research_topic("planning/plan.md", "code-")
        assert result is None

    def test_extract_wrong_prefix(self):
        """Verify None returned for wrong prefix."""
        result = extract_research_topic("03_research/web-auth/request.md", "code-")
        assert result is None


class TestExtractSubplanIndex:
    """Test extract_subplan_index helper."""

    def test_extract_done_1(self):
        """Verify extraction of done_1."""
        result = extract_subplan_index("05_implementation/done_1")
        assert result == 1

    def test_extract_done_10(self):
        """Verify extraction of done_10."""
        result = extract_subplan_index("05_implementation/done_10")
        assert result == 10

    def test_extract_no_match(self):
        """Verify None returned for non-matching paths."""
        result = extract_subplan_index("05_implementation/complete")
        assert result is None

    def test_extract_wrong_directory(self):
        """Verify None returned for wrong directory."""
        result = extract_subplan_index("06_review/done_1")
        assert result is None


class TestIntegration:
    """Integration tests for the full router flow."""

    def test_full_workflow_simulation(self, mock_context):
        """Simulate a complete workflow from planning to completion."""
        # Track the workflow
        workflow_log = []

        class LoggingHandler:
            def __init__(self, name):
                self.name = name

            def enter(self, state, ctx):
                workflow_log.append(f"enter:{self.name}")
                return {}

            def handle_event(self, event, state, ctx):
                workflow_log.append(f"handle:{self.name}:{event.path}")
                # Transition based on event
                if self.name == "planning" and "plan.md" in (event.path or ""):
                    return {}, "implementing"
                elif self.name == "implementing" and "done_1" in (event.path or ""):
                    return {"__exit__": 0}, None
                return {}, None

        phases = {
            "planning": LoggingHandler("planning"),
            "implementing": LoggingHandler("implementing"),
        }
        router = WorkflowEventRouter(phases)

        state = {"phase": "planning"}

        with patch("agentmux.sessions.state_store.write_state"):
            # Event 1: Plan written
            event1 = WorkflowEvent(kind="file.created", path="planning/plan.md")
            updates, exit = router.handle(event1, state, mock_context)
            assert exit is None
            assert state["phase"] == "implementing"

            # Event 2: Implementation done
            event2 = WorkflowEvent(kind="file.created", path="implementation/done_1")
            updates, exit = router.handle(event2, state, mock_context)
            assert exit == 0

        # Verify workflow sequence
        # Note: When transitioning, the same event is passed to the new phase's handler
        assert workflow_log == [
            "enter:planning",
            "handle:planning:planning/plan.md",
            "enter:implementing",
            "handle:implementing:planning/plan.md",  # Same event passed
            "handle:implementing:implementation/done_1",
        ]


class TestEventSpecRouting:
    """Test declarative EventSpec evaluation in the router."""

    def _make_ctx(self, tmp_path):
        """Build a minimal mock context with a real feature_dir."""
        files = MagicMock(spec=RuntimeFiles)
        files.feature_dir = tmp_path
        files.state = tmp_path / "state.json"
        runtime = MagicMock()
        agents = {"coder": MagicMock(spec=AgentConfig)}
        return PipelineContext(
            files=files,
            runtime=runtime,
            agents=agents,
            max_review_iterations=3,
            prompts={},
            github_config=GitHubConfig(),
            workflow_settings=WorkflowSettings(),
        )

    def test_spec_fires_when_path_matches_and_ready(self, tmp_path):
        """EventSpec with matching path and ready predicate dispatches logical event."""
        (tmp_path / "05_implementation").mkdir()
        marker = tmp_path / "05_implementation" / "done_1"
        marker.touch()

        received = []

        class SpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="done_marker",
                        watch_paths=("05_implementation/done_*",),
                        is_ready=lambda p, c, s: (c.files.feature_dir / p).exists(),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": SpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "done_marker"
        assert received[0].path == "05_implementation/done_1"

    def test_spec_does_not_fire_when_not_ready(self, tmp_path):
        """EventSpec with matching path but not-ready predicate is suppressed."""
        received = []

        class SpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="done_marker",
                        watch_paths=("05_implementation/done_*",),
                        is_ready=lambda p, c, s: (c.files.feature_dir / p).exists(),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": SpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        # File doesn't exist → is_ready returns False → no dispatch
        assert received == []

    def test_spec_does_not_fire_for_non_matching_path(self, tmp_path):
        """EventSpec ignores events whose path doesn't match any watch_paths."""
        received = []

        class SpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="done_marker",
                        watch_paths=("05_implementation/done_*",),
                        is_ready=lambda p, c, s: True,
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": SpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.created", path="06_review/review.md")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert received == []

    def test_spec_ignores_non_file_events(self, tmp_path):
        """EventSpec routing only considers file.created / file.activity."""
        received = []

        class SpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="done_marker",
                        watch_paths=("05_implementation/done_*",),
                        is_ready=lambda p, c, s: True,
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": SpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(
            kind="interruption.pane_exited",
            payload={"pane_id": "coder.0"},
        )
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert received == []

    def test_empty_specs_falls_through_to_raw_event(self, tmp_path):
        """Handler returning empty specs receives raw WorkflowEvent."""
        received = []

        class EmptySpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return ()

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": EmptySpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "file.created"  # raw kind preserved
        assert received[0].path == "05_implementation/done_1"

    def test_no_get_event_specs_falls_through_to_raw_event(self, tmp_path):
        """Handler without get_event_specs method receives raw WorkflowEvent."""
        received = []

        class LegacyHandler:
            def enter(self, state, ctx):
                return {}

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": LegacyHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "file.created"

    def test_multi_spec_only_matching_one_fires(self, tmp_path):
        """When multiple specs exist, only the one whose path matches fires."""
        received = []

        class MultiSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="plan_written",
                        watch_paths=("02_planning/plan.md",),
                        is_ready=lambda p, c, s: True,
                    ),
                    EventSpec(
                        name="done_marker",
                        watch_paths=("05_implementation/done_*",),
                        is_ready=lambda p, c, s: True,
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": MultiSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.created", path="05_implementation/done_3")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "done_marker"
        assert received[0].path == "05_implementation/done_3"

    def test_spec_with_state_dependent_ready(self, tmp_path):
        """is_ready can inspect state to decide whether to fire."""
        received = []

        class StatefulSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="review_ready",
                        watch_paths=("06_review/review.md",),
                        is_ready=lambda p, c, s: not s.get("awaiting_summary"),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"reviewing": StatefulSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "reviewing", "awaiting_summary": True}

        event = WorkflowEvent(kind="file.created", path="06_review/review.md")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        # awaiting_summary=True → is_ready returns False → suppressed
        assert received == []

        # Flip the flag — now it should fire
        state["awaiting_summary"] = False
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "review_ready"

    def test_spec_fires_on_file_activity_too(self, tmp_path):
        """EventSpec routing also triggers on file.activity events."""
        (tmp_path / "05_implementation").mkdir()
        marker = tmp_path / "05_implementation" / "done_1"
        marker.touch()

        received = []

        class SpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="done_marker",
                        watch_paths=("05_implementation/done_*",),
                        is_ready=lambda p, c, s: (c.files.feature_dir / p).exists(),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"implementing": SpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "implementing"}

        event = WorkflowEvent(kind="file.activity", path="05_implementation/done_1")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "done_marker"


class TestToolSpecRouting:
    """Test ToolSpec-based tool.* event routing in the router."""

    def _make_ctx(self, tmp_path):
        """Build a minimal mock context with a real feature_dir."""
        files = MagicMock(spec=RuntimeFiles)
        files.feature_dir = tmp_path
        files.state = tmp_path / "state.json"
        runtime = MagicMock()
        agents = {"coder": MagicMock(spec=AgentConfig)}
        return PipelineContext(
            files=files,
            runtime=runtime,
            agents=agents,
            max_review_iterations=3,
            prompts={},
            github_config=GitHubConfig(),
            workflow_settings=WorkflowSettings(),
        )

    def test_tool_event_matching_spec_dispatches_logical_event(self, tmp_path):
        """tool.* event matching a ToolSpec dispatches WorkflowEvent(kind=spec.name)."""
        from agentmux.workflow.event_router import ToolSpec

        received = []

        class ToolSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return ()

            def get_tool_specs(self):
                return (
                    ToolSpec(
                        name="architecture_submitted",
                        tool_names=("submit_architecture",),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"architecting": ToolSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "architecting"}

        event = WorkflowEvent(
            kind="tool.submit_architecture",
            payload={"status": "ok"},
        )
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(event, state, ctx)

        assert len(received) == 1
        assert received[0].kind == "architecture_submitted"
        assert received[0].payload == {"status": "ok"}

    def test_tool_event_non_matching_returns_empty(self, tmp_path):
        """Non-matching tool name returns ({}, None)."""
        from agentmux.workflow.event_router import ToolSpec

        received = []

        class ToolSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return ()

            def get_tool_specs(self):
                return (
                    ToolSpec(
                        name="plan_submitted",
                        tool_names=("submit_plan",),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"planning": ToolSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "planning"}

        event = WorkflowEvent(
            kind="tool.submit_architecture",
            payload={"status": "ok"},
        )
        with patch("agentmux.sessions.state_store.write_state"):
            updates, next_phase = router.handle(event, state, ctx)

        assert updates == {}
        assert next_phase is None
        assert received == []

    def test_backward_compat_file_events_still_route_via_eventspec(self, tmp_path):
        """file.created events still route via EventSpec when handler has both specs."""
        from agentmux.workflow.event_router import EventSpec, ToolSpec

        file_received = []
        tool_received = []

        class DualSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return (
                    EventSpec(
                        name="plan_written",
                        watch_paths=("02_planning/plan.md",),
                        is_ready=lambda p, c, s: True,
                    ),
                )

            def get_tool_specs(self):
                return (
                    ToolSpec(
                        name="plan_submitted",
                        tool_names=("submit_plan",),
                    ),
                )

            def handle_event(self, event, state, ctx):
                if event.kind.startswith("tool."):
                    tool_received.append(event)
                else:
                    file_received.append(event)
                return {}, None

        router = WorkflowEventRouter({"planning": DualSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "planning"}

        # File event should still route via EventSpec
        file_event = WorkflowEvent(kind="file.created", path="02_planning/plan.md")
        with patch("agentmux.sessions.state_store.write_state"):
            router.handle(file_event, state, ctx)

        assert len(file_received) == 1
        assert file_received[0].kind == "plan_written"
        assert file_received[0].path == "02_planning/plan.md"
        assert tool_received == []

    def test_tool_event_with_multiple_tool_names_in_spec(self, tmp_path):
        """A single ToolSpec can match multiple bare tool names."""
        from agentmux.workflow.event_router import ToolSpec

        received = []

        class ToolSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return ()

            def get_tool_specs(self):
                return (
                    ToolSpec(
                        name="any_submission",
                        tool_names=(
                            "submit_architecture",
                            "submit_plan",
                            "submit_review",
                        ),
                    ),
                )

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"architecting": ToolSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "architecting"}

        for tool_name in ("submit_architecture", "submit_plan", "submit_review"):
            event = WorkflowEvent(kind=f"tool.{tool_name}", payload={"tool": tool_name})
            with patch("agentmux.sessions.state_store.write_state"):
                router.handle(event, state, ctx)

        assert len(received) == 3
        assert all(r.kind == "any_submission" for r in received)

    def test_handler_without_get_tool_specs_ignores_tool_events(self, tmp_path):
        """Handler without get_tool_specs returns empty for tool.* events."""
        received = []

        class NoToolSpecHandler:
            def enter(self, state, ctx):
                return {}

            def get_event_specs(self):
                return ()

            def handle_event(self, event, state, ctx):
                received.append(event)
                return {}, None

        router = WorkflowEventRouter({"architecting": NoToolSpecHandler()})
        ctx = self._make_ctx(tmp_path)
        state = {"phase": "architecting"}

        event = WorkflowEvent(kind="tool.submit_architecture", payload={})
        with patch("agentmux.sessions.state_store.write_state"):
            updates, next_phase = router.handle(event, state, ctx)

        assert updates == {}
        assert next_phase is None
        assert received == []
