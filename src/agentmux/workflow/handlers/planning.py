"""Event-driven handler for planning phase.

The planning phase is where the planner creates execution plans based on
the architecture document produced by the architect in the architecting phase.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import yaml

from agentmux.workflow.event_catalog import EVENT_CHANGES_REQUESTED, EVENT_PLAN_WRITTEN
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.execution_plan import load_execution_plan
from agentmux.workflow.handlers.base import BaseToolHandler, ToolHandlerEntry
from agentmux.workflow.handoff_artifacts import (
    _write_yaml,
    generate_execution_plan_yaml,
    generate_plan_md,
    generate_subplan_md,
    generate_tasks_md,
)
from agentmux.workflow.phase_helpers import (
    handle_research_done,
    handle_research_request,
    load_plan_meta,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_change_prompt,
    build_planner_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class PlanningHandler(BaseToolHandler):
    """Event-driven handler for planning phase.

    The planner receives the architecture document and creates execution plans.
    """

    def _get_tool_handlers(self) -> tuple[ToolHandlerEntry, ...]:
        return (
            ToolHandlerEntry(
                name="plan",
                tool_names=("submit_plan",),
                handler=lambda s, e, st, c: s._handle_plan(e, st, c),
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
                handler=lambda s, e, st, c: handle_research_done(e, st, c, "planner"),
            ),
        )

    def get_event_specs(self) -> Sequence[EventSpec]:
        return ()

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering planning phase.

        Sends planner prompt (initial or changes).
        """
        is_replan = (
            state.get("last_event") == EVENT_CHANGES_REQUESTED
            and ctx.files.changes.exists()
        )
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(
                ctx.files.planning_dir
                / ("changes_prompt.md" if is_replan else "planner_prompt.md")
            ),
            build_change_prompt(ctx.files, ctx.agents.get("planner"))
            if is_replan
            else build_planner_prompt(ctx.files, ctx.agents.get("planner")),
        )
        send_to_role(ctx, "planner", prompt_file)
        return {}

    def _handle_plan(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle unified plan submission (plan.yaml version 2)."""
        yaml_path = ctx.files.planning_dir / "plan.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

        # Materialize plan_N.md and tasks_N.md for each sub-plan, always
        # regenerating so replans don't leave stale derived artifacts.
        new_indices: set[int] = set()
        for sp in data.get("subplans", []):
            idx = sp["index"]
            new_indices.add(idx)
            plan_md = ctx.files.planning_dir / f"plan_{idx}.md"
            plan_md.parent.mkdir(parents=True, exist_ok=True)
            plan_md.write_text(generate_subplan_md(sp), encoding="utf-8")
            tasks_md = ctx.files.planning_dir / f"tasks_{idx}.md"
            tasks_md.write_text(generate_tasks_md(sp), encoding="utf-8")

        # Remove stale plan_N.md / tasks_N.md from a previous plan.
        for old in ctx.files.planning_dir.glob("plan_*.md"):
            try:
                n = int(old.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            if n not in new_indices:
                old.unlink(missing_ok=True)
                (ctx.files.planning_dir / f"tasks_{n}.md").unlink(missing_ok=True)

        # Materialize execution_plan.yaml, always regenerating so it stays in sync
        # with the new plan.
        ep_path = ctx.files.planning_dir / "execution_plan.yaml"
        _write_yaml(ep_path, generate_execution_plan_yaml(data))

        # Materialize plan.md from plan_overview, always regenerating.
        plan_md_path = ctx.files.planning_dir / "plan.md"
        if data.get("plan_overview"):
            plan_md_path.parent.mkdir(parents=True, exist_ok=True)
            plan_md_path.write_text(generate_plan_md(data), encoding="utf-8")

        load_execution_plan(ctx.files.planning_dir)
        meta = load_plan_meta(ctx.files.planning_dir)
        needs_design = bool(meta.get("needs_design")) and "designer" in ctx.agents

        # Delete changes.md if exists.
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()

        # Deactivate and kill planner - their work is done.
        ctx.runtime.deactivate("planner")
        ctx.runtime.kill_primary("planner")

        next_phase = "designing" if needs_design else "implementing"
        return {"last_event": EVENT_PLAN_WRITTEN}, next_phase
