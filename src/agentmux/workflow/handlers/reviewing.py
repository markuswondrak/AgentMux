"""Event-driven handler for reviewing phase."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import yaml

from agentmux.agent_labels import role_display_label
from agentmux.workflow.event_catalog import (
    EVENT_RESUMED,
    EVENT_REVIEW_FAILED,
    EVENT_REVIEW_PASSED,
)
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.handlers.base import BaseToolHandler, ToolHandlerEntry
from agentmux.workflow.handoff_artifacts import (
    load_review_text,
    review_yaml_has_verdict,
)
from agentmux.workflow.phase_helpers import (
    load_plan_meta,
    select_reviewer_type,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_reviewer_expert_prompt,
    build_reviewer_logic_prompt,
    build_reviewer_prompt,
    build_reviewer_quality_prompt,
    build_reviewer_summary_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext

_REVIEWER_ROLE_MAP = {
    "logic": "reviewer_logic",
    "quality": "reviewer_quality",
    "expert": "reviewer_expert",
}


def _summary_ready(path: str, ctx: PipelineContext, state: dict) -> bool:
    return bool(state.get("awaiting_summary")) and ctx.files.summary.exists()


_SPECS = (
    EventSpec(
        name="summary_ready",
        watch_paths=("08_completion/summary.md",),
        is_ready=_summary_ready,
    ),
)


class ReviewingHandler(BaseToolHandler):
    """Event-driven handler for reviewing phase."""

    def _get_tool_handlers(self) -> tuple[ToolHandlerEntry, ...]:
        return (
            ToolHandlerEntry(
                name="review",
                tool_names=("submit_review",),
                handler=lambda s, e, st, c: s._handle_review(e, st, c),
            ),
        )

    def get_event_specs(self) -> Sequence[EventSpec]:
        return _SPECS

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering reviewing phase.

        Sends reviewer prompt based on review_strategy routing.
        """
        # On resume, if the reviewer already wrote review output leave it in
        # place. seed_existing_files() will publish file events and handle_event()
        # will process the verdict correctly.
        if state.get("last_event") == EVENT_RESUMED and (
            ctx.files.review.exists() or review_yaml_has_verdict(ctx.files.review_dir)
        ):
            return {}

        if ctx.files.review.exists():
            ctx.files.review.unlink()
        review_yaml = ctx.files.review_dir / "review.yaml"
        if review_yaml.exists():
            review_yaml.unlink()

        # Load plan_meta and determine reviewer type
        plan_meta = load_plan_meta(ctx.files.planning_dir)
        reviewer_type = select_reviewer_type(plan_meta)

        # Map reviewer types to their configuration
        reviewer_config = {
            "logic": {
                "role": "reviewer_logic",
                "prompt_builder": build_reviewer_logic_prompt,
                "prompt_path": ctx.files.review_logic_prompt,
            },
            "quality": {
                "role": "reviewer_quality",
                "prompt_builder": build_reviewer_quality_prompt,
                "prompt_path": ctx.files.review_quality_prompt,
            },
            "expert": {
                "role": "reviewer_expert",
                "prompt_builder": build_reviewer_expert_prompt,
                "prompt_path": ctx.files.review_expert_prompt,
            },
        }

        config = reviewer_config[reviewer_type]

        # Build the prompt: specialized agent prompts are self-contained,
        # the generic reviewer combines agent prompt + command prompt.
        reviewer_role = config["role"]
        if reviewer_type == "logic":
            full_prompt = build_reviewer_logic_prompt(
                ctx.files, ctx.agents.get(reviewer_role)
            )
        elif reviewer_type == "quality":
            full_prompt = build_reviewer_quality_prompt(
                ctx.files, ctx.agents.get(reviewer_role)
            )
        elif reviewer_type == "expert":
            full_prompt = build_reviewer_expert_prompt(
                ctx.files, ctx.agents.get(reviewer_role)
            )
        else:
            # Fallback: generic reviewer combines agent + command prompt
            agent_prompt = build_reviewer_prompt(
                ctx.files, agent=ctx.agents.get(reviewer_role)
            )
            command_prompt = build_reviewer_prompt(ctx.files, is_review=True)
            full_prompt = f"{agent_prompt}\n\n{command_prompt}"

        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(config["prompt_path"]),
            full_prompt,
        )
        send_to_role(
            ctx,
            config["role"],
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, config["role"], state=state
            ),
        )
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events: Tool-Events via base, File-Events via EventSpec."""
        # File events from EventSpec
        if event.kind == "summary_ready":
            return self._handle_summary_written(ctx)
        # Tool events from BaseToolHandler
        return super().handle_event(event, state, ctx)

    def _handle_review(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle review submission via tool event."""
        # YAML is agent-written and already validated by the MCP signal tool.
        yaml_path = ctx.files.review_dir / "review.yaml"
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        verdict = data.get("verdict", "").lower()

        review_iteration = int(state.get("review_iteration", 0))

        # Archive this review for history (review_0.md, review_1.md, …).
        archive_path = ctx.files.review_dir / f"review_{review_iteration}.md"
        review_text = load_review_text(
            ctx.files.review_dir,
            materialize_markdown=True,
        )
        if review_text is not None:
            archive_path.write_text(review_text, encoding="utf-8")

        if verdict == "pass":
            ctx.runtime.finish_many("coder")
            ctx.runtime.kill_primary("coder")
            return self._request_summary(state, ctx)

        if verdict == "fail":
            if review_iteration >= ctx.max_review_iterations:
                return {"last_event": EVENT_REVIEW_FAILED}, "completing"

            ctx.files.fix_request.write_text(review_text or "", encoding="utf-8")
            return {
                "last_event": EVENT_REVIEW_FAILED,
                "review_iteration": review_iteration + 1,
            }, "fixing"

        return {}, None

    def _request_summary(
        self,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Send summary prompt to reviewer and wait for summary.md."""
        plan_meta = load_plan_meta(ctx.files.planning_dir)
        reviewer_type = select_reviewer_type(plan_meta)
        reviewer_role = _REVIEWER_ROLE_MAP[reviewer_type]

        # Clear any stale summary from a previous run
        if ctx.files.summary.exists():
            ctx.files.summary.unlink()

        summary_prompt_path = ctx.files.completion_dir / "summary_prompt.md"
        ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(summary_prompt_path),
            build_reviewer_summary_prompt(ctx.files, ctx.agents.get(reviewer_role)),
        )
        send_to_role(
            ctx,
            reviewer_role,
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, reviewer_role, state=state
            ),
        )
        return {"last_event": EVENT_REVIEW_PASSED, "awaiting_summary": True}, None

    def _handle_summary_written(
        self,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Summary is ready — kill reviewer and move to completing."""
        plan_meta = load_plan_meta(ctx.files.planning_dir)
        reviewer_type = select_reviewer_type(plan_meta)
        reviewer_role = _REVIEWER_ROLE_MAP[reviewer_type]
        ctx.runtime.kill_primary(reviewer_role)
        return {"awaiting_summary": False}, "completing"
