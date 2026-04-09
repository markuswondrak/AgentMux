"""Event-driven handler for architecting phase.

The architecting phase is where the architect creates the technical architecture
document (architecture.md). This is separate from planning to allow a clean
separation between "What/With what" (architect) and "How/When" (planner).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from agentmux.workflow.event_catalog import EVENT_ARCHITECTURE_WRITTEN
from agentmux.workflow.event_router import (
    EventSpec,
    ToolSpec,
    WorkflowEvent,
)
from agentmux.workflow.phase_helpers import (
    dispatch_research_task,
    notify_research_complete,
    research_role_from_payload,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_architect_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class ArchitectingHandler:
    """Event-driven handler for architecting phase.

    The architect creates the technical architecture document (architecture.md).
    Research tasks are dispatched to code-researcher and web-researcher as needed.
    When architecture.md is written, the phase transitions to 'planning'.
    """

    def get_event_specs(self) -> Sequence[EventSpec]:
        return ()

    def get_tool_specs(self) -> Sequence[ToolSpec]:
        return (
            ToolSpec(name="architecture", tool_names=("submit_architecture",)),
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
        match event.kind:
            case "architecture":
                return self._handle_architecture(event, state, ctx)
            case "research_code_req":
                return self._handle_research_code_req(event, state, ctx)
            case "research_web_req":
                return self._handle_research_web_req(event, state, ctx)
            case "research_done":
                return self._handle_research_done(event, state, ctx)
            case _:
                return {}, None

    def _handle_architecture(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle architecture submission via tool event."""
        # architecture.md is agent-written and already validated by submit_architecture.
        md_path = ctx.files.planning_dir / "architecture.md"

        # Delete changes.md if exists (we're moving forward)
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()

        # Deactivate and kill architect - their work is done
        ctx.runtime.deactivate("architect")
        ctx.runtime.kill_primary("architect")

        _ = md_path  # used by the orchestrator directly; no transformation needed
        # Transition to planning phase (planner takes over)
        return {"last_event": EVENT_ARCHITECTURE_WRITTEN}, "planning"

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

        return notify_research_complete(role, topic, state, ctx, "architect")

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

        return notify_research_complete(role, topic, state, ctx, "architect")
