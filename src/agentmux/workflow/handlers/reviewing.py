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


class ReviewingHandler:
    """Event-driven handler for reviewing phase."""

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering reviewing phase.

        Sends reviewer prompt based on review_strategy routing.
        """
        # On resume, if the reviewer already wrote review.md leave it in place.
        # seed_existing_files() will publish FILE_EVENT_CREATED for it and
        # handle_event() will process the verdict correctly.
        if state.get("last_event") == "resumed" and ctx.files.review.exists():
            return {}

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
        reviewer_role = config["role"]
        agent_prompt = config["prompt_builder"](
            ctx.files, ctx.agents.get(reviewer_role)
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
        """Handle events for reviewing phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for review written
        if path == "06_review/review.md":
            return self._handle_review_written(state, ctx)

        # Check for implementation summary written by reviewer
        if path == "08_completion/summary.md" and state.get("awaiting_summary"):
            return self._handle_summary_written(ctx)

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

        review_iteration = int(state.get("review_iteration", 0))

        # Archive this review for history (review_0.md, review_1.md, …).
        # review.md itself is kept so the summary prompt and monitor can still
        # reference it by the canonical name.
        archive_path = ctx.files.review_dir / f"review_{review_iteration}.md"
        archive_path.write_text(review_text, encoding="utf-8")

        if first_line == "verdict: pass":
            ctx.runtime.finish_many("coder")
            ctx.runtime.kill_primary("coder")
            return self._request_summary(state, ctx)

        if first_line == "verdict: fail":
            if review_iteration >= ctx.max_review_iterations:
                return {"last_event": "review_failed"}, "completing"

            ctx.files.fix_request.write_text(review_text, encoding="utf-8")
            return {
                "last_event": "review_failed",
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
        return {"last_event": "review_passed", "awaiting_summary": True}, None

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
