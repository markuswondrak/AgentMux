"""Event-driven handler for architecting phase.

The architecting phase is where the architect creates the technical architecture
document (architecture.md). This is separate from planning to allow a clean
separation between "What/With what" (architect) and "How/When" (planner).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import (
    EventSpec,
    WorkflowEvent,
    extract_research_topic,
)
from agentmux.workflow.phase_helpers import (
    apply_role_preferences,
    dispatch_research_task,
    notify_research_complete,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_architect_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


def _file_exists(path: str, ctx: PipelineContext, state: dict) -> bool:
    return (ctx.files.feature_dir / path).exists()


_SPECS = (
    EventSpec(
        name="architecture_written",
        watch_paths=("02_planning/architecture.md",),
        is_ready=_file_exists,
    ),
    EventSpec(
        name="code_research_requested",
        watch_paths=("03_research/code-*/request.md",),
        is_ready=_file_exists,
    ),
    EventSpec(
        name="web_research_requested",
        watch_paths=("03_research/web-*/request.md",),
        is_ready=_file_exists,
    ),
    EventSpec(
        name="code_research_done",
        watch_paths=("03_research/code-*/done",),
        is_ready=_file_exists,
    ),
    EventSpec(
        name="web_research_done",
        watch_paths=("03_research/web-*/done",),
        is_ready=_file_exists,
    ),
)


class ArchitectingHandler:
    """Event-driven handler for architecting phase.

    The architect creates the technical architecture document (architecture.md).
    Research tasks are dispatched to code-researcher and web-researcher as needed.
    When architecture.md is written, the phase transitions to 'planning'.
    """

    def get_event_specs(self) -> tuple[EventSpec, ...]:
        return _SPECS

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering architecting phase."""
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.planning_dir / "architect_prompt.md"),
            build_architect_prompt(ctx.files, ctx.agents.get("architect")),
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
        if event.kind == "architecture_written":
            return self._handle_architecture_written(state, ctx)

        if event.kind == "code_research_requested":
            topic = extract_research_topic(event.path or "", "code-")
            if topic:
                return dispatch_research_task("code-researcher", topic, state, ctx)

        if event.kind == "web_research_requested":
            topic = extract_research_topic(event.path or "", "web-")
            if topic:
                return dispatch_research_task("web-researcher", topic, state, ctx)

        if event.kind == "code_research_done":
            topic = extract_research_topic(event.path or "", "code-")
            if topic:
                return notify_research_complete(
                    "code-researcher", topic, state, ctx, "architect"
                )

        if event.kind == "web_research_done":
            topic = extract_research_topic(event.path or "", "web-")
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
