"""Event-driven handler for failed phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import WorkflowEvent

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class FailedHandler:
    """Event-driven handler for failed phase.

    This is the simplest handler - it just returns exit failure on any event.
    """

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering failed phase.

        Does nothing - failure is handled by handle_event.
        """
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for failed phase.

        Returns exit failure for any event.
        """
        return {"__exit__": 1}, None
