"""Event-driven handler for architecting phase.

The architecting phase is where the architect creates the technical architecture
document (architecture.md). This is separate from planning to allow a clean
separation between "What/With what" (architect) and "How/When" (planner).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import (
    WorkflowEvent,
    extract_research_topic,
    path_matches,
)
from agentmux.workflow.phase_helpers import (
    apply_role_preferences,
    dispatch_research_task,
    filter_file_created_event,
    notify_research_complete,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_architect_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class ArchitectingHandler:
    """Event-driven handler for architecting phase.

    The architect creates the technical architecture document (architecture.md).
    Research tasks are dispatched to code-researcher and web-researcher as needed.
    When architecture.md is written, the phase transitions to 'planning'.
    """

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering architecting phase."""
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.planning_dir / "architect_prompt.md"),
            build_architect_prompt(ctx.files),
        )
        send_to_role(ctx, "architect", prompt_file)
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for architecting phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for architecture completion
        if path == "02_planning/architecture.md":
            return self._handle_architecture_written(state, ctx)

        # Check for research request
        if path_matches("03_research/code-*/request.md", path):
            topic = extract_research_topic(path, "code-")
            if topic:
                return dispatch_research_task("code-researcher", topic, state, ctx)

        if path_matches("03_research/web-*/request.md", path):
            topic = extract_research_topic(path, "web-")
            if topic:
                return dispatch_research_task("web-researcher", topic, state, ctx)

        # Check for research done
        if path_matches("03_research/code-*/done", path):
            topic = extract_research_topic(path, "code-")
            if topic:
                return notify_research_complete(
                    "code-researcher", topic, state, ctx, "architect"
                )

        if path_matches("03_research/web-*/done", path):
            topic = extract_research_topic(path, "web-")
            if topic:
                return notify_research_complete(
                    "web-researcher", topic, state, ctx, "architect"
                )

        return {}, None

    def _handle_architecture_written(
        self,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle architecture written event.

        When architecture.md is written, transition to planning phase
        where the planner will create execution plans.
        """
        # Check if architecture file exists
        if not ctx.files.architecture.exists():
            return {}, None

        # Apply approved preferences from architect
        apply_role_preferences(ctx, "architect")

        # Delete changes.md if exists (we're moving forward)
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()

        # Deactivate and kill architect - their work is done
        ctx.runtime.deactivate("architect")
        ctx.runtime.kill_primary("architect")

        # Transition to planning phase (planner takes over)
        return {"last_event": "architecture_written"}, "planning"
