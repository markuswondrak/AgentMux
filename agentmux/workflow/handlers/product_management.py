"""Event-driven handler for product_management phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import (
    PhaseHandler,
    WorkflowEvent,
    extract_research_topic,
    path_matches,
)
from agentmux.workflow.phase_helpers import send_to_role, write_phase
from agentmux.workflow.preference_memory import (
    apply_preference_proposal,
    load_preference_proposal,
    proposal_artifact_for_source,
)
from agentmux.workflow.prompts import (
    build_code_researcher_prompt,
    build_product_manager_prompt,
    build_web_researcher_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from ..transitions import PipelineContext


class ProductManagementHandler:
    """Event-driven handler for product_management phase."""

    def enter(self, state: dict, ctx: "PipelineContext") -> dict:
        """Called when entering product_management phase.

        Sends product-manager prompt.
        """
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(
                ctx.files.product_management_dir / "product_manager_prompt.md"
            ),
            build_product_manager_prompt(ctx.files),
        )
        send_to_role(ctx, "product-manager", prompt_file)
        return {}  # No state updates

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle events for product_management phase."""
        if event.kind != "file.created":
            return {}, None

        path = event.path
        if path is None:
            return {}, None

        # Check for pm completion
        if path == "01_product_management/done":
            return self._handle_pm_completed(state, ctx)

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

    def _handle_pm_completed(
        self,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle product management completion."""
        # Apply approved preferences
        proposal_path = proposal_artifact_for_source(ctx.files, "product-manager")
        proposal = load_preference_proposal(proposal_path)
        if proposal:
            apply_preference_proposal(ctx.files.project_dir, proposal)

        # Kill product-manager pane
        ctx.runtime.kill_primary("product-manager")

        # Transition to planning
        return {"last_event": "pm_completed"}, "planning"

    def _dispatch_research(
        self,
        role: str,
        topic: str,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Dispatch a research task."""
        # Check if already dispatched
        tasks_key = (
            "research_tasks" if role == "code-researcher" else "web_research_tasks"
        )
        tasks = dict(state.get(tasks_key, {}))
        if topic in tasks:
            return {}, None

        # Remove done marker if exists
        prefix = "code-" if role == "code-researcher" else "web-"
        done_marker = ctx.files.research_dir / f"{prefix}{topic}" / "done"
        if done_marker.exists():
            done_marker.unlink()

        # Build prompt and spawn task
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

        # Update state
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
        # Finish task
        ctx.runtime.finish_task(role, topic)

        # Notify product-manager
        prefix = "code-" if role == "code-researcher" else "web-"
        summary_path = ctx.files.relative_path(
            ctx.files.research_dir / f"{prefix}{topic}" / "summary.md"
        )
        role_name = "Code-research" if role == "code-researcher" else "Web research"
        ctx.runtime.notify(
            "product-manager",
            f"{role_name} on '{topic}' is complete. Read {summary_path} and continue from there.",
        )

        # Update state
        tasks_key = (
            "research_tasks" if role == "code-researcher" else "web_research_tasks"
        )
        tasks = dict(state.get(tasks_key, {}))
        tasks[topic] = "done"
        return {tasks_key: tasks}, None
