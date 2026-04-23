"""Tests for FailedHandler."""

from __future__ import annotations

from unittest.mock import MagicMock

from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import FailedHandler


class TestFailedHandler:
    """Tests for FailedHandler."""

    def test_enter_returns_empty(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test that enter() returns empty updates."""
        handler = FailedHandler()

        result = handler.enter(empty_state, mock_ctx)

        assert result.updates == {}

    def test_handle_event_returns_exit_failure(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that any event returns exit failure."""
        handler = FailedHandler()
        event = WorkflowEvent(kind="file.created", path="any/path")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert updates == {"__exit__": 1}
        assert next_phase is None
