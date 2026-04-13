"""Event-driven handler for reviewing phase."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import yaml

from agentmux.agent_labels import role_display_label
from agentmux.runtime import ReviewerSpec
from agentmux.workflow.event_catalog import (
    EVENT_RESUMED,
    EVENT_REVIEW_FAILED,
    EVENT_REVIEW_PASSED,
)
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.handlers.base import BaseToolHandler, ToolHandlerEntry
from agentmux.workflow.handoff_artifacts import generate_review_md
from agentmux.workflow.phase_helpers import (
    load_plan_meta,
    select_reviewer_roles,
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

# Review prompt builders keyed by role suffix
_REVIEWER_PROMPT_BUILDERS = {
    "logic": build_reviewer_logic_prompt,
    "quality": build_reviewer_quality_prompt,
    "expert": build_reviewer_expert_prompt,
}


def _all_done(active_reviews: dict) -> bool:
    return bool(active_reviews) and all(
        s == "completed" for s in active_reviews.values()
    )


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
    """Event-driven handler for reviewing phase with parallel reviewer support."""

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

    # -------------------------------------------------------------------------
    # enter() — parallel reviewer dispatch
    # -------------------------------------------------------------------------

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called when entering reviewing phase.

        Dispatches reviewer roles in parallel via send_reviewers_many().
        On resume, skips reviewers that already have results in review_results.
        """
        plan_meta = load_plan_meta(ctx.files.planning_dir)
        reviewer_roles = select_reviewer_roles(plan_meta)

        # Determine which roles still need reviewing (resume support)
        review_results = dict(state.get("review_results", {}))
        active_reviews = {
            _REVIEWER_ROLE_MAP[role]: "pending" for role in reviewer_roles
        }

        # On resume: skip completed reviewers
        is_resume = state.get("last_event") == EVENT_RESUMED
        if is_resume:
            for role in list(active_reviews.keys()):
                if role in review_results:
                    active_reviews[role] = "completed"

            # If all are already completed, transition to summary or fixing
            all_completed = all(s == "completed" for s in active_reviews.values())
            if all_completed and active_reviews:
                # Check if any review was a fail
                any_failed = any(
                    review_results.get(_REVIEWER_ROLE_MAP.get(r, r), {}).get("verdict")
                    == "fail"
                    for r in reviewer_roles
                )
                if any_failed:
                    return self._trigger_fixing(state, ctx, review_results)
                return self._request_summary(state, ctx)

        # Clear stale review outputs for roles we're about to re-dispatch
        for role_suffix in reviewer_roles:
            pane_role = _REVIEWER_ROLE_MAP[role_suffix]
            if active_reviews.get(pane_role) == "pending":
                review_file = ctx.files.review_dir / f"review_{pane_role}.yaml"
                if review_file.exists():
                    review_file.unlink()

        # Build ReviewerSpec list for pending roles only
        reviewer_specs = self._build_reviewer_specs(
            reviewer_roles, active_reviews, ctx, state
        )

        if reviewer_specs:
            ctx.runtime.send_reviewers_many(reviewer_specs)

        # Initialize state
        return {
            "active_reviews": active_reviews,
            "review_results": review_results,
        }

    def _build_reviewer_specs(
        self,
        reviewer_roles: list[str],
        active_reviews: dict[str, str],
        ctx: PipelineContext,
        state: dict,
    ) -> list[ReviewerSpec]:
        """Build ReviewerSpec list for roles that still need reviewing."""
        specs: list[ReviewerSpec] = []
        for role_suffix in reviewer_roles:
            pane_role = _REVIEWER_ROLE_MAP[role_suffix]
            if active_reviews.get(pane_role) != "pending":
                continue

            prompt_builder = _REVIEWER_PROMPT_BUILDERS.get(role_suffix)
            if prompt_builder is None:
                # Fallback: generic reviewer
                agent_prompt = build_reviewer_prompt(
                    ctx.files, agent=ctx.agents.get(pane_role)
                )
                command_prompt = build_reviewer_prompt(ctx.files, is_review=True)
                full_prompt = f"{agent_prompt}\n\n{command_prompt}"
            else:
                full_prompt = prompt_builder(ctx.files, ctx.agents.get(pane_role))

            # Write the prompt to a role-specific file
            prompt_filename = f"review_{role_suffix}_prompt.md"
            prompt_path = ctx.files.review_dir / prompt_filename
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(full_prompt, encoding="utf-8")
            prompt_file = ctx.files.relative_path(prompt_path)

            specs.append(
                ReviewerSpec(
                    role=pane_role,
                    prompt_file=prompt_file,
                    display_label=role_display_label(
                        ctx.files.feature_dir, pane_role, state=state
                    ),
                )
            )
        return specs

    # -------------------------------------------------------------------------
    # handle_event — dispatch to file or tool event handlers
    # -------------------------------------------------------------------------

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle events: Tool-Events via base, File-Events via EventSpec."""
        if event.kind == "summary_ready":
            return self._handle_summary_written(ctx)
        return super().handle_event(event, state, ctx)

    # -------------------------------------------------------------------------
    # _handle_review — verdict aggregation
    # -------------------------------------------------------------------------

    def _handle_review(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Handle review submission via tool event.

        Scans every role-specific review_*.yaml file available at event time,
        aggregates verdicts, and only after the full scan decides the verdict.
        This avoids dropping feedback when two reviewers fail concurrently or
        when a fail would short-circuit a sibling's still-unread file.
        """
        review_results = dict(state.get("review_results", {}))
        active_reviews = dict(state.get("active_reviews", {}))
        review_iteration = int(state.get("review_iteration", 0))

        review_dir = ctx.files.review_dir
        for review_file in sorted(review_dir.glob("review_reviewer_*.yaml")):
            role_name = review_file.stem[len("review_") :]

            if role_name in review_results:
                continue

            try:
                data = yaml.safe_load(review_file.read_text(encoding="utf-8"))
            except (yaml.YAMLError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            verdict = data.get("verdict", "").lower()
            if verdict not in ("pass", "fail"):
                continue

            review_text = self._generate_review_text(data)
            archive_path = review_dir / f"review_{review_iteration}_{role_name}.md"
            if review_text is not None:
                archive_path.write_text(review_text, encoding="utf-8")

            review_results[role_name] = {
                "verdict": verdict,
                "review_text": review_text or "",
            }
            if role_name in active_reviews:
                active_reviews[role_name] = "completed"

        any_failed = any(r.get("verdict") == "fail" for r in review_results.values())
        if any_failed:
            self._kill_pending_reviewers(ctx, active_reviews)
            return self._handle_fail(
                state, ctx, review_results, active_reviews, review_iteration
            )

        if _all_done(active_reviews):
            return self._request_summary(state, ctx)

        return {
            "review_results": review_results,
            "active_reviews": active_reviews,
        }, None

    def _kill_pending_reviewers(
        self, ctx: PipelineContext, active_reviews: dict
    ) -> None:
        """Tear down reviewer panes that are still marked 'pending'.

        Called whenever we abandon the reviewing phase before every reviewer
        has submitted — prevents leaked reviewer panes running against stale
        code once fixing has started.
        """
        for role, status in list(active_reviews.items()):
            if status == "pending":
                ctx.runtime.kill_primary(role)
                active_reviews[role] = "killed"

    def _generate_review_text(self, data: dict) -> str | None:
        """Generate review markdown from an already-parsed review data dict."""
        if not isinstance(data, dict):
            return None
        return generate_review_md(data)

    def _handle_fail(
        self,
        state: dict,
        ctx: PipelineContext,
        review_results: dict,
        active_reviews: dict,
        review_iteration: int,
    ) -> tuple[dict, str | None]:
        """Handle a fail verdict — aggregate feedback and trigger fixing."""
        if review_iteration >= ctx.max_review_iterations:
            return {
                "last_event": EVENT_REVIEW_FAILED,
                "review_results": review_results,
                "active_reviews": active_reviews,
            }, "completing"

        # Aggregate feedback from ALL completed reviews
        aggregated = self._aggregate_fix_feedback(review_results)
        ctx.files.fix_request.write_text(aggregated, encoding="utf-8")

        return {
            "last_event": EVENT_REVIEW_FAILED,
            "review_iteration": review_iteration + 1,
            "review_results": review_results,
            "active_reviews": active_reviews,
        }, "fixing"

    def _aggregate_fix_feedback(self, review_results: dict) -> str:
        """Combine feedback from all completed reviews into fix_request.md."""
        sections: list[str] = []
        for role_name, result in sorted(review_results.items()):
            review_text = result.get("review_text", "")
            verdict = result.get("verdict", "unknown")
            if not review_text:
                continue
            sections.append(f"## Review: {role_name} (verdict: {verdict})")
            sections.append("")
            sections.append(review_text)
            sections.append("")
        return "\n".join(sections)

    def _trigger_fixing(
        self,
        state: dict,
        ctx: PipelineContext,
        review_results: dict,
    ) -> tuple[dict, str | None]:
        """Trigger fixing from resume when all reviews are already done."""
        review_iteration = int(state.get("review_iteration", 0))
        if review_iteration >= ctx.max_review_iterations:
            return {
                "last_event": EVENT_REVIEW_FAILED,
                "review_results": review_results,
            }, "completing"

        aggregated = self._aggregate_fix_feedback(review_results)
        ctx.files.fix_request.write_text(aggregated, encoding="utf-8")

        return {
            "last_event": EVENT_REVIEW_FAILED,
            "review_iteration": review_iteration + 1,
            "review_results": review_results,
        }, "fixing"

    # -------------------------------------------------------------------------
    # _request_summary — only after ALL reviews pass
    # -------------------------------------------------------------------------

    def _request_summary(
        self,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Send summary prompt to reviewer and wait for summary.md.

        Only called when ALL active reviewers have passed.
        Sends to reviewer_logic as the coordinator role.
        """
        plan_meta = load_plan_meta(ctx.files.planning_dir)
        reviewer_roles = select_reviewer_roles(plan_meta)
        # Use the first role as coordinator (typically "logic")
        first = reviewer_roles[0] if reviewer_roles else "logic"
        coordinator_role = _REVIEWER_ROLE_MAP.get(first, "reviewer_logic")

        # All reviewers have passed — the coder panes are no longer needed.
        # Tear them down before dispatching the summary so we don't leak
        # implementation panes across the summary/completing transition.
        ctx.runtime.finish_many("coder")
        ctx.runtime.kill_primary("coder")

        # Clear any stale summary from a previous run
        if ctx.files.summary.exists():
            ctx.files.summary.unlink()

        summary_prompt_path = ctx.files.completion_dir / "summary_prompt.md"
        ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(summary_prompt_path),
            build_reviewer_summary_prompt(ctx.files, ctx.agents.get(coordinator_role)),
        )
        send_to_role(
            ctx,
            coordinator_role,
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, coordinator_role, state=state
            ),
        )
        return {"last_event": EVENT_REVIEW_PASSED, "awaiting_summary": True}, None

    # -------------------------------------------------------------------------
    # _handle_summary_written — kill all reviewer panes
    # -------------------------------------------------------------------------

    def _handle_summary_written(
        self,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Summary is ready — kill all reviewer panes and move to completing."""
        plan_meta = load_plan_meta(ctx.files.planning_dir)
        reviewer_roles = select_reviewer_roles(plan_meta)

        # Kill all reviewer panes
        for role_suffix in reviewer_roles:
            pane_role = _REVIEWER_ROLE_MAP[role_suffix]
            ctx.runtime.kill_primary(pane_role)

        return {"awaiting_summary": False}, "completing"
