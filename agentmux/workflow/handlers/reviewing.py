"""Event-driven handler for reviewing phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.agent_labels import role_display_label
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.phase_helpers import (
    filter_file_created_event,
    load_plan_meta,
    select_reviewer_type,
    send_to_role,
)
from agentmux.workflow.prompts import (
    build_reviewer_expert_prompt,
    build_reviewer_logic_prompt,
    build_reviewer_prompt,
    build_reviewer_quality_prompt,
    write_prompt_file,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class ReviewingHandler:
    """Event-driven handler for reviewing phase."""

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering reviewing phase.

        Sends reviewer prompt based on review_strategy routing.
        """
        if ctx.files.review.exists():
            ctx.files.review.unlink()

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

        # Build the command prompt (review.md) combined with agent prompt
        agent_prompt = config["prompt_builder"](ctx.files)
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
        """Handle events for reviewing phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for review written
        if path == "06_review/review.md":
            return self._handle_review_written(state, ctx)

        return {}, None

    def _handle_review_written(
        self,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle review written event."""
        if not ctx.files.review.exists():
            return {}, None

        review_text = ctx.files.review.read_text(encoding="utf-8")
        first_line = (
            review_text.splitlines()[0].strip().lower()
            if review_text.splitlines()
            else ""
        )

        if first_line == "verdict: pass":
            ctx.runtime.finish_many("coder")
            ctx.runtime.kill_primary("coder")
            return {"last_event": "review_passed"}, "completing"

        if first_line == "verdict: fail":
            review_iteration = int(state.get("review_iteration", 0))
            if review_iteration >= ctx.max_review_iterations:
                return {"last_event": "review_failed"}, "completing"

            # Copy review to fix_request
            ctx.files.fix_request.write_text(
                ctx.files.review.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            return {
                "last_event": "review_failed",
                "review_iteration": review_iteration + 1,
            }, "fixing"

        return {}, None
