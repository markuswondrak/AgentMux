"""Tests for DesigningHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import DesigningHandler


class TestDesigningHandler:
    """Tests for DesigningHandler."""

    def test_enter_sends_designer_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends designer prompt."""
        handler = DesigningHandler()

        with (
            patch(
                "agentmux.workflow.handlers.designing.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.designing.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.designing.build_designer_prompt"
            ) as mock_build,
            patch(
                "agentmux.workflow.handlers.designing.role_display_label"
            ) as mock_label,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "designer prompt"
            mock_label.return_value = "[designer] design"

            handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once_with(
                mock_ctx,
                "designer",
                Path("/mock/prompt.md"),
                display_label="[designer] design",
            )

    def test_handle_design_written(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition on design.md creation."""
        handler = DesigningHandler()
        event = WorkflowEvent(kind="design_written", path="05_design/design.md")

        # Create the design file so is_ready predicate passes
        mock_ctx.files.design.parent.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.design.write_text("design")

        _, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.deactivate.assert_called_once_with("designer")
        assert next_phase == "implementing"
