"""Tests for extracted phase helper functions (research dispatch)."""

from __future__ import annotations

from unittest.mock import MagicMock

from agentmux.workflow.phase_helpers import (
    dispatch_research_task,
    notify_research_complete,
)


class TestPhaseHelpers:
    """Tests for extracted phase helper functions."""

    def test_dispatch_research_task_skips_already_dispatched(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test that already dispatched tasks are not re-dispatched."""
        state = {"research_tasks": {"auth": "dispatched"}}
        updates, next_phase = dispatch_research_task(
            "code-researcher", "auth", state, mock_ctx
        )

        assert updates == {}
        assert next_phase is None
        mock_ctx.runtime.spawn_task.assert_not_called()

    def test_notify_research_complete_updates_state(self, mock_ctx: MagicMock) -> None:
        """Test that research completion updates state correctly."""
        state = {"research_tasks": {"auth": "dispatched"}}
        updates, next_phase = notify_research_complete(
            "code-researcher", "auth", state, mock_ctx, "architect"
        )

        assert updates["research_tasks"]["auth"] == "done"
        assert next_phase is None
        mock_ctx.runtime.finish_task.assert_called_once_with("code-researcher", "auth")
        mock_ctx.runtime.notify.assert_called_once()
