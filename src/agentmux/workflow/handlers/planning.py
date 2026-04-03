"""Event-driven handler for planning phase.

The planning phase is where the planner creates execution plans based on
the architecture document produced by the architect in the architecting phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import (
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
    build_change_prompt,
    build_planner_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class PlanningHandler:
    """Event-driven handler for planning phase.

    The planner receives the architecture document and creates execution plans.
    """

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering planning phase.

        Sends planner prompt (initial or changes).
        """
        is_replan = (
            state.get("last_event") == "changes_requested"
            and ctx.files.changes.exists()
        )
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(
                ctx.files.planning_dir
                / ("changes_prompt.txt" if is_replan else "planner_prompt.md")
            ),
            build_change_prompt(ctx.files)
            if is_replan
            else build_planner_prompt(ctx.files),
        )
        send_to_role(ctx, "planner", prompt_file)
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for planning phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for plan completion (all three files must exist)
        if path in (
            "02_planning/plan.md",
            "02_planning/execution_plan.json",
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

        # Check for research done - notify planner (not architect)
        if path_matches("03_research/code-*/done", path):
            topic = extract_research_topic(path, "code-")
            if topic:
                return notify_research_complete(
                    "code-researcher", topic, state, ctx, "planner"
                )

        if path_matches("03_research/web-*/done", path):
            topic = extract_research_topic(path, "web-")
            if topic:
                return notify_research_complete(
                    "web-researcher", topic, state, ctx, "planner"
                )

        return {}, None

    def _handle_plan_written(
        self,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle plan written event.

        All three files (plan.md, execution_plan.json, plan_meta.json) must exist.
        """
        # Check if all required files exist
        if not (ctx.files.plan.exists() and ctx.files.execution_plan.exists()):
            return {}, None

        meta_path = ctx.files.planning_dir / "plan_meta.json"
        if not meta_path.exists():
            return {}, None

        # Apply approved preferences from planner
        apply_role_preferences(ctx, "planner")

        # Load execution plan and meta
        load_execution_plan(ctx.files.planning_dir)
        meta = load_plan_meta(ctx.files.planning_dir)
        needs_design = bool(meta.get("needs_design")) and "designer" in ctx.agents

        # Delete changes.md if exists
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()

        # Deactivate and kill planner - their work is done
        ctx.runtime.deactivate("planner")
        ctx.runtime.kill_primary("planner")

        # Determine next phase
        next_phase = "designing" if needs_design else "implementing"
        return {"last_event": "plan_written"}, next_phase
