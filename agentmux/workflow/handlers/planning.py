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
from agentmux.workflow.phase_helpers import load_plan_meta, send_to_role
from agentmux.workflow.preference_memory import (
    apply_preference_proposal,
    load_preference_proposal,
    proposal_artifact_for_source,
)
from agentmux.workflow.prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_code_researcher_prompt,
    build_web_researcher_prompt,
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
        if event.kind != "file.created":
            return {}, None

        path = event.path
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
                return self._dispatch_research("code-researcher", topic, state, ctx)

        if path_matches("03_research/web-*/request.md", path):
            topic = extract_research_topic(path, "web-")
            if topic:
                return self._dispatch_research("web-researcher", topic, state, ctx)

        # Check for research done
        if path_matches("03_research/code-*/done", path):
            topic = extract_research_topic(path, "code-")
            if topic:
                return self._notify_research_done("code-researcher", topic, state, ctx)

        if path_matches("03_research/web-*/done", path):
            topic = extract_research_topic(path, "web-")
            if topic:
                return self._notify_research_done("web-researcher", topic, state, ctx)

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
        proposal_path = proposal_artifact_for_source(ctx.files, "architect")
        proposal = load_preference_proposal(proposal_path)
        if proposal:
            apply_preference_proposal(ctx.files.project_dir, proposal)

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

    def _dispatch_research(
        self,
        role: str,
        topic: str,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Dispatch a research task."""
        tasks_key = (
            "research_tasks" if role == "code-researcher" else "web_research_tasks"
        )
        tasks = dict(state.get(tasks_key, {}))
        if topic in tasks:
            return {}, None

        prefix = "code-" if role == "code-researcher" else "web-"
        done_marker = ctx.files.research_dir / f"{prefix}{topic}" / "done"
        if done_marker.exists():
            done_marker.unlink()

        research_dir = ctx.files.research_dir / f"{prefix}{topic}"
        prompt_builder = (
            build_code_researcher_prompt
            if role == "code-researcher"
            else build_web_researcher_prompt
        )
        write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(research_dir / "prompt.md"),
            prompt_builder(topic, ctx.files),
        )
        ctx.runtime.spawn_task(role, topic, research_dir)

        tasks[topic] = "dispatched"
        return {tasks_key: tasks}, None

    def _notify_research_done(
        self,
        role: str,
        topic: str,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Notify that research is complete."""
        ctx.runtime.finish_task(role, topic)

        prefix = "code-" if role == "code-researcher" else "web-"
        summary_path = ctx.files.relative_path(
            ctx.files.research_dir / f"{prefix}{topic}" / "summary.md"
        )
        role_name = "Code-research" if role == "code-researcher" else "Web research"
        ctx.runtime.notify(
            "architect",
            f"{role_name} on '{topic}' is complete. Read {summary_path} and continue from there.",
        )

        tasks_key = (
            "research_tasks" if role == "code-researcher" else "web_research_tasks"
        )
        tasks = dict(state.get(tasks_key, {}))
        tasks[topic] = "done"
        return {tasks_key: tasks}, None
