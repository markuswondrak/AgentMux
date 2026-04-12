"""Event-driven handler for architecting phase.

The architecting phase is where the architect creates the technical architecture
document (architecture.md). This is separate from planning to allow a clean
separation between "What/With what" (architect) and "How/When" (planner).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from agentmux.workflow.event_catalog import EVENT_ARCHITECTURE_WRITTEN
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.handlers.base import BaseToolHandler, ToolHandlerEntry
from agentmux.workflow.phase_helpers import (
    handle_research_done,
    handle_research_request,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_architect_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class ArchitectingHandler(BaseToolHandler):
    """Event-driven handler for architecting phase.

    The architect creates the technical architecture document (architecture.md).
    Research tasks are dispatched to code-researcher and web-researcher as needed.
    When architecture.md is written, the phase transitions to 'planning'.
    """

    def _get_tool_handlers(self) -> tuple[ToolHandlerEntry, ...]:
        return (
            ToolHandlerEntry(
                name="architecture",
                tool_names=("submit_architecture",),
                handler=lambda s, e, st, c: s._handle_architecture(e, st, c),
            ),
            ToolHandlerEntry(
                name="research_code_req",
                tool_names=("research_dispatch_code",),
                handler=lambda s, e, st, c: handle_research_request(
                    "code-researcher", e, st, c
                ),
            ),
            ToolHandlerEntry(
                name="research_web_req",
                tool_names=("research_dispatch_web",),
                handler=lambda s, e, st, c: handle_research_request(
                    "web-researcher", e, st, c
                ),
            ),
            ToolHandlerEntry(
                name="research_done",
                tool_names=("submit_research_done",),
                handler=lambda s, e, st, c: handle_research_done(e, st, c, "architect"),
            ),
        )

    def get_event_specs(self) -> Sequence[EventSpec]:
        return ()

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering architecting phase."""
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.architecting_dir / "architect_prompt.md"),
            build_architect_prompt(ctx.files, ctx.agents.get("architect")),
        )
        send_to_role(ctx, "architect", prompt_file)
        return {}

    def _handle_architecture(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle architecture submission via tool event."""
        # architecture.md is agent-written and already validated by submit_architecture.
        md_path = ctx.files.architecting_dir / "architecture.md"

        # Delete changes.md if exists (we're moving forward)
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()

        # Deactivate and kill architect - their work is done
        ctx.runtime.deactivate("architect")
        ctx.runtime.kill_primary("architect")

        _ = md_path  # used by the orchestrator directly; no transformation needed
        # Transition to planning phase (planner takes over)
        return {"last_event": EVENT_ARCHITECTURE_WRITTEN}, "planning"
