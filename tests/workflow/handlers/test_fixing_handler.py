"""Tests for FixingHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import FixingHandler


class TestFixingHandler:
    """Tests for FixingHandler."""

    def test_enter_sends_fix_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends fix prompt."""
        handler = FixingHandler()

        with (
            patch("agentmux.workflow.handlers.fixing.write_prompt_file") as mock_write,
            patch("agentmux.workflow.handlers.fixing.send_to_role") as mock_send,
            patch("agentmux.workflow.handlers.fixing.build_fix_prompt") as mock_build,
            patch("agentmux.workflow.handlers.fixing.role_display_label") as mock_label,
            patch("agentmux.workflow.handlers.fixing.reset_markers"),
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "fix prompt"
            mock_label.return_value = "[coder] fix 1"

            handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once_with(
                mock_ctx,
                "coder",
                Path("/mock/prompt.md"),
                display_label="[coder] fix 1",
            )

    def test_handle_implementation_completed(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition on done_1 marker."""
        handler = FixingHandler()
        event = WorkflowEvent(kind="done", path="06_implementation/done_1")

        # Create the done marker so is_ready predicate passes
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.implementation_dir / "done_1").touch()

        _, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"
