"""Event-driven handler for planning phase.

The planning phase is where the planner creates execution plans based on
the architecture document produced by the architect in the architecting phase.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import yaml

from agentmux.workflow.event_catalog import EVENT_CHANGES_REQUESTED, EVENT_PLAN_WRITTEN
from agentmux.workflow.event_router import (
    EventSpec,
    ToolSpec,
    WorkflowEvent,
)
from agentmux.workflow.execution_plan import load_execution_plan
from agentmux.workflow.handoff_artifacts import (
    _write_yaml,
    generate_execution_plan_yaml,
    generate_plan_md,
    generate_subplan_md,
    generate_tasks_md,
)
from agentmux.workflow.phase_helpers import (
    dispatch_research_task,
    load_plan_meta,
    notify_research_complete,
    research_role_from_payload,
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

    def get_event_specs(self) -> Sequence[EventSpec]:
        return ()

    def get_tool_specs(self) -> Sequence[ToolSpec]:
        return (
            ToolSpec(name="plan", tool_names=("submit_plan",)),
            ToolSpec(
                name="research_code_req",
                tool_names=("research_dispatch_code",),
            ),
            ToolSpec(
                name="research_web_req",
                tool_names=("research_dispatch_web",),
            ),
            ToolSpec(
                name="research_done",
                tool_names=("submit_research_done",),
            ),
        )

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

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for planning phase."""
        match event.kind:
            case "plan":
                return self._handle_plan(event, state, ctx)
            case "research_code_req":
                return self._handle_research_code_req(event, state, ctx)
            case "research_web_req":
                return self._handle_research_web_req(event, state, ctx)
            case "research_done":
                return self._handle_research_done(event, state, ctx)
            case _:
                return {}, None

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

    def _handle_research_code_req(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle code research request via tool event."""
        payload = event.payload.get("payload", {})
        topic = payload.get("topic", "")
        if not topic:
            return {}, None

        # Write request.md before dispatching (side-effect ordering requirement)
        req_dir = ctx.files.research_dir / f"code-{topic}"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_path = req_dir / "request.md"
        if not req_path.exists():
            questions = payload.get("questions", [])
            scope_hints = payload.get("scope_hints", [])
            content = (
                f"# Research Request: {topic}\n\n"
                f"## Context\n{payload.get('context', '')}\n\n"
                f"## Questions\n"
                + "\n".join(f"- {q}" for q in questions)
                + (
                    "\n\n## Scope Hints\n" + "\n".join(f"- {h}" for h in scope_hints)
                    if scope_hints
                    else ""
                )
            )
            req_path.write_text(content, encoding="utf-8")

        return dispatch_research_task("code-researcher", topic, state, ctx)

    def _handle_research_web_req(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle web research request via tool event."""
        payload = event.payload.get("payload", {})
        topic = payload.get("topic", "")
        if not topic:
            return {}, None

        # Write request.md before dispatching (side-effect ordering requirement)
        req_dir = ctx.files.research_dir / f"web-{topic}"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_path = req_dir / "request.md"
        if not req_path.exists():
            questions = payload.get("questions", [])
            scope_hints = payload.get("scope_hints", [])
            content = (
                f"# Research Request: {topic}\n\n"
                f"## Context\n{payload.get('context', '')}\n\n"
                f"## Questions\n"
                + "\n".join(f"- {q}" for q in questions)
                + (
                    "\n\n## Scope Hints\n" + "\n".join(f"- {h}" for h in scope_hints)
                    if scope_hints
                    else ""
                )
            )
            req_path.write_text(content, encoding="utf-8")

        return dispatch_research_task("web-researcher", topic, state, ctx)

    def _handle_research_done(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle research completion via tool event."""
        payload = event.payload.get("payload", {})
        topic = payload.get("topic", "")
        role = research_role_from_payload(payload)
        if not topic or role is None:
            return {}, None

        return notify_research_complete(role, topic, state, ctx, "planner")
