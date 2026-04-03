"""Event-driven handler for designing phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.agent_labels import role_display_label
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.phase_helpers import (
    filter_file_created_event,
    send_to_role,
)
from agentmux.workflow.prompts import build_designer_prompt, write_prompt_file

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class DesigningHandler:
    """Event-driven handler for designing phase."""

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering designing phase.

        Sends designer prompt.
        """
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.design_dir / "designer_prompt.md"),
            build_designer_prompt(ctx.files),
        )
        send_to_role(
            ctx,
            "designer",
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, "designer", state=state
            ),
        )
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for designing phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for design completion
        if path == "04_design/design.md":
            ctx.runtime.deactivate("designer")
            return {"last_event": "design_written"}, "implementing"

        return {}, None
