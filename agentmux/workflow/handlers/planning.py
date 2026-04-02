"""Event-driven handler for planning phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import (
    PhaseHandler,
    WorkflowEvent,
    extract_research_topic,
    path_matches,
)
from agentmux.workflow.execution_plan import load_execution_plan
from agentmux.workflow.phase_helpers import (
    apply_role_preferences,
    dispatch_research_task,
    filter_file_created_event,
    load_plan_meta,
    notify_research_complete,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_architect_prompt,
    build_change_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class PlanningHandler:
    """Event-driven handler for planning phase."""

    def enter(self, state: dict, ctx: "PipelineContext") -> dict:
        """Called when entering planning phase.

        Sends architect prompt (initial or changes).
        """
        is_replan = (
            state.get("last_event") == "changes_requested"
            and ctx.files.changes.exists()
        )
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(
                ctx.files.planning_dir
                / ("changes_prompt.txt" if is_replan else "architect_prompt.md")
            ),
            build_change_prompt(ctx.files)
            if is_replan
            else build_architect_prompt(ctx.files),
        )
        send_to_role(ctx, "architect", prompt_file)
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle events for planning phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for plan completion (all three files must exist)
        if path in (
            "02_planning/plan.md",
            "02_planning/tasks.md",
            "02_planning/plan_meta.json",
        ):
            return self._handle_plan_written(state, ctx)

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

    def _handle_plan_written(
        self,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle plan written event.

        All three files (plan.md, tasks.md, plan_meta.json) must exist.
        """
        # Check if all required files exist
        if not (ctx.files.plan.exists() and ctx.files.tasks.exists()):
            return {}, None

        meta_path = ctx.files.planning_dir / "plan_meta.json"
        if not meta_path.exists():
            return {}, None

        # Apply approved preferences
        apply_role_preferences(ctx, "architect")

        # Load execution plan and meta
        load_execution_plan(ctx.files.planning_dir)
        meta = load_plan_meta(ctx.files.planning_dir)
        needs_design = bool(meta.get("needs_design")) and "designer" in ctx.agents

        # Delete changes.md if exists
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()

        # Deactivate and kill architect
        ctx.runtime.deactivate("architect")
        ctx.runtime.kill_primary("architect")

        # Determine next phase
        next_phase = "designing" if needs_design else "implementing"
        return {"last_event": "plan_written"}, next_phase
