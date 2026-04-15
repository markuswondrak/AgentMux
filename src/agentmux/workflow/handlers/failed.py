"""Event-driven handler for failed phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.phase_result import PhaseResult

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class FailedHandler:
    """Event-driven handler for failed phase.

    Declares a catch-all EventSpec so that any file event triggers
    the exit-failure response.
    """

    def get_event_specs(self) -> tuple[EventSpec, ...]:
        return (
            EventSpec(
                name="any_file",
                watch_paths=("*",),
                is_ready=lambda p, c, s: True,
            ),
        )

    def enter(self, state: dict, ctx: PipelineContext) -> PhaseResult:
        """Called when entering failed phase.

        Does nothing - failure is handled by handle_event.
        """
        return PhaseResult({})

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
