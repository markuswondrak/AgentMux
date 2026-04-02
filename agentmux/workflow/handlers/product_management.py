"""Event-driven handler for product_management phase."""

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
    build_product_manager_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from ..transitions import PipelineContext


class ProductManagementHandler:
    """Event-driven handler for product_management phase."""

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
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
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for product_management phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for pm completion
        if path == "01_product_management/done":
            return self._handle_pm_completed(state, ctx)

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
                    "code-researcher", topic, state, ctx, "product-manager"
                )

        if path_matches("03_research/web-*/done", path):
            topic = extract_research_topic(path, "web-")
            if topic:
                return notify_research_complete(
                    "web-researcher", topic, state, ctx, "product-manager"
                )

        return {}, None

    def _handle_pm_completed(
        self,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle product management completion."""
        # Apply approved preferences
        apply_role_preferences(ctx, "product-manager")

        # Kill product-manager pane
        ctx.runtime.kill_primary("product-manager")

        # Transition to planning
        return {"last_event": "pm_completed"}, "planning"
