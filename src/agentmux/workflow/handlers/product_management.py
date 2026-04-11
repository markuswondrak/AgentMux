"""Event-driven handler for product_management phase."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, ClassVar

from agentmux.workflow.event_catalog import EVENT_PM_COMPLETED
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.handlers.base import BaseToolHandler, ToolHandlerEntry
from agentmux.workflow.phase_helpers import (
    handle_research_request,
    notify_research_complete,
    research_role_from_payload,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_product_manager_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from ..transitions import PipelineContext


class ProductManagementHandler(BaseToolHandler):
    """Event-driven handler for product_management phase."""

    _TOOL_HANDLERS: ClassVar[tuple[ToolHandlerEntry, ...]] = (
        ToolHandlerEntry(
            name="pm_done",
            tool_names=("submit_pm_done",),
            handler=lambda s, e, st, c: s._handle_pm_done(e, st, c),
        ),
        ToolHandlerEntry(
            name="research_code_req",
            tool_names=("research_dispatch_code",),
            handler=lambda s, e, st, c: s._handle_research_code_req(e, st, c),
        ),
        ToolHandlerEntry(
            name="research_web_req",
            tool_names=("research_dispatch_web",),
            handler=lambda s, e, st, c: s._handle_research_web_req(e, st, c),
        ),
        ToolHandlerEntry(
            name="research_done",
            tool_names=("submit_research_done",),
            handler=lambda s, e, st, c: s._handle_research_done(e, st, c),
        ),
    )

    def get_event_specs(self) -> Sequence[EventSpec]:
        return ()

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

    def _handle_pm_done(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle product management completion via tool event."""
        # Kill product-manager pane
        ctx.runtime.kill_primary("product-manager")

        # Transition to architecting
        return {"last_event": EVENT_PM_COMPLETED}, "architecting"

    def _handle_research_code_req(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle code research request via tool event."""
        return handle_research_request("code-researcher", event, state, ctx)

    def _handle_research_web_req(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle web research request via tool event."""
        return handle_research_request("web-researcher", event, state, ctx)

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

        return notify_research_complete(role, topic, state, ctx, "product-manager")
