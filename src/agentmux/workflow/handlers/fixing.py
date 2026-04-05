"""Event-driven handler for fixing phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.agent_labels import role_display_label
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.phase_helpers import (
    reset_markers,
    send_to_role,
)
from agentmux.workflow.prompts import build_fix_prompt, write_prompt_file

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class FixingHandler:
    """Event-driven handler for fixing phase."""

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering fixing phase.

        Sends fix prompt to coder.
        """
        if state.get("last_event") == "review_failed":
            reset_markers(ctx.files.implementation_dir, "done_*")

        ctx.runtime.kill_primary("coder")
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.review_dir / "fix_prompt.txt"),
            build_fix_prompt(ctx.files),
        )
        send_to_role(
            ctx,
            "coder",
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, "coder", state=state
            ),
        )
        return {
            "completed_subplans": [],
        }

    def get_event_specs(self) -> tuple[EventSpec, ...]:
        return (
            EventSpec(
                name="fix_done",
                watch_paths=("05_implementation/done_1",),
                is_ready=lambda path, ctx, state: (
                    ctx.files.feature_dir / path
                ).exists(),
            ),
        )

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for fixing phase."""
        if event.kind == "fix_done":
            ctx.runtime.finish_many("coder")
            ctx.runtime.deactivate("coder")
            return {"last_event": "implementation_completed"}, "reviewing"
        return {}, None
