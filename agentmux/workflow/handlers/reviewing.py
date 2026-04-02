"""Event-driven handler for reviewing phase."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentmux.workflow.event_router import PhaseHandler, WorkflowEvent
from agentmux.workflow.phase_helpers import (
    filter_file_created_event,
    send_to_role,
)
from agentmux.workflow.prompts import build_reviewer_prompt, write_prompt_file
from agentmux.agent_labels import role_display_label

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


class ReviewingHandler:
    """Event-driven handler for reviewing phase."""

    def enter(self, state: dict, ctx: "PipelineContext") -> dict:
        """Called when entering reviewing phase.

        Sends reviewer prompt.
        """
        if ctx.files.review.exists():
            ctx.files.review.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.review_dir / "review_prompt.md"),
            build_reviewer_prompt(ctx.files, is_review=True),
        )
        send_to_role(
            ctx,
            "reviewer",
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, "reviewer", state=state
            ),
        )
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: "PipelineContext",
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
        ctx: "PipelineContext",
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
