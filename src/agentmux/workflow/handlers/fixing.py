"""Event-driven handler for fixing phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.agent_labels import role_display_label
from agentmux.workflow.event_catalog import (
    EVENT_IMPLEMENTATION_COMPLETED,
    EVENT_REVIEW_FAILED,
)
from agentmux.workflow.event_router import (
    EventSpec,
    WorkflowEvent,
    extract_subplan_index,
)
from agentmux.workflow.handlers.base import BaseToolHandler, ToolHandlerEntry
from agentmux.workflow.phase_helpers import (
    reset_markers,
    send_to_role,
)
from agentmux.workflow.prompts import build_fix_prompt, write_prompt_file

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class FixingHandler(BaseToolHandler):
    """Event-driven handler for fixing phase."""

    def _get_tool_handlers(self) -> tuple[ToolHandlerEntry, ...]:
        return (
            ToolHandlerEntry(
                name="done",
                tool_names=("submit_done",),
                handler=lambda s, e, st, c: s._handle_done(e, st, c),
            ),
        )

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering fixing phase.

        Sends fix prompt to coder.
        """
        if state.get("last_event") == EVENT_REVIEW_FAILED:
            reset_markers(ctx.files.implementation_dir, "done_*")

        ctx.runtime.kill_primary("coder")
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.review_dir / "fix_prompt.md"),
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
        return ()

    def _handle_done(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        payload = event.payload.get("payload", {})
        subplan_index = payload.get("subplan_index")
        if subplan_index is None and event.path is not None:
            subplan_index = extract_subplan_index(event.path)
        if subplan_index is not None:
            # Write done_N marker for tracking (idempotent)
            done_n_path = ctx.files.implementation_dir / f"done_{subplan_index}"
            if not done_n_path.exists():
                done_n_path.touch()
            ctx.runtime.finish_many("coder")
            ctx.runtime.deactivate("coder")
            return {"last_event": EVENT_IMPLEMENTATION_COMPLETED}, "reviewing"
        return {}, None
