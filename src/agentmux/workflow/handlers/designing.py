"""Event-driven handler for designing phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.agent_labels import role_display_label
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.phase_helpers import send_to_role
from agentmux.workflow.prompts import build_designer_prompt, write_prompt_file

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


def _file_exists(path: str, ctx: PipelineContext, state: dict) -> bool:
    return (ctx.files.feature_dir / path).exists()


_SPECS = (
    EventSpec(
        name="design_written",
        watch_paths=("04_design/design.md",),
        is_ready=_file_exists,
    ),
)


class DesigningHandler:
    """Event-driven handler for designing phase."""

    def get_event_specs(self) -> tuple[EventSpec, ...]:
        return _SPECS

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
        if event.kind == "design_written":
            ctx.runtime.deactivate("designer")
            return {"last_event": "design_written"}, "implementing"
        return {}, None
