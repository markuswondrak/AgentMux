"""Event-driven handler for product_management phase."""

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
    build_product_manager_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from ..transitions import PipelineContext


def _file_exists(path: str, ctx: PipelineContext, state: dict) -> bool:
    return (ctx.files.feature_dir / path).exists()


_SPECS = (
    EventSpec(
        name="pm_completed",
        watch_paths=("01_product_management/done",),
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
            build_product_manager_prompt(ctx.files, ctx.agents.get("product-manager")),
        )
        send_to_role(ctx, "product-manager", prompt_file)
        return {}  # No state updates

    def get_event_specs(self) -> tuple[EventSpec, ...]:
        return _SPECS

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events for product_management phase."""
        if event.kind == "pm_completed":
            return self._handle_pm_completed(state, ctx)

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
                    "code-researcher", topic, state, ctx, "product-manager"
                )

        if event.kind == "web_research_done":
            topic = extract_research_topic(event.path or "", "web-")
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

        # Transition to architecting
        return {"last_event": "pm_completed"}, "architecting"
