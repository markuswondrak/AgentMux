from __future__ import annotations

import json
from typing import Any

from .plan_parser import split_plan_into_subplans
from .prompts import (
    build_change_prompt,
    build_coder_subplan_prompt,
    build_docs_prompt,
    build_fix_prompt,
    write_prompt_file,
)
from .state import (
    cleanup_feature_dir,
    commit_changes,
    load_state,
    now_iso,
    parse_review_verdict,
    update_state,
    write_state,
)
from .tmux import (
    create_agent_pane,
    kill_agent_pane,
    send_prompt,
    tmux_pane_exists,
)
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext


def _mark(ctx: PipelineContext, status: str) -> None:
    """Mark a status as handled so it won't re-fire."""
    ctx.handled.add(status)


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------


def _has_multiple_subplans(state: dict[str, Any], ctx: PipelineContext) -> bool:
    subplan_paths = split_plan_into_subplans(ctx.files.plan, ctx.files.feature_dir)
    return len(subplan_paths) > 1


def _all_coders_done(state: dict[str, Any], ctx: PipelineContext) -> bool:
    expected = int(state.get("subplan_count", 0))
    if expected <= 0:
        expected = len(ctx.coder_panes)
    if expected <= 0:
        return False
    return all(
        (ctx.files.feature_dir / f"done_{idx}").exists()
        for idx in range(1, expected + 1)
    )


def _review_verdict_is_fail(state: dict[str, Any], ctx: PipelineContext) -> bool:
    review_text = ctx.files.review.read_text(encoding="utf-8")
    verdict = parse_review_verdict(review_text)
    review_iteration = int(state.get("review_iteration", 0))
    return verdict == "fail" and review_iteration < ctx.max_review_iterations


def _has_docs_agent(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return "docs" in ctx.agents


def _needs_design(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return bool(state.get("needs_design")) and "designer" in ctx.agents


# ---------------------------------------------------------------------------
# Composite guards
# ---------------------------------------------------------------------------


def guard_plan_ready_design(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled and _needs_design(state, ctx)


def guard_plan_ready_multi(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled and _has_multiple_subplans(state, ctx)


def guard_plan_ready_single(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled


def guard_design_ready(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled


def guard_coders_done(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return _all_coders_done(state, ctx)


def guard_review_fail(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled and _review_verdict_is_fail(state, ctx)


def guard_review_pass_docs(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled and _has_docs_agent(state, ctx)


def guard_review_pass_no_docs(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled


# ---------------------------------------------------------------------------
# Handlers — one per transition row
# ---------------------------------------------------------------------------


def handle_plan_ready_design(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 1: plan_ready (needs design) -> designer_requested."""
    if not tmux_pane_exists(ctx.panes.get("designer")):
        ctx.panes["designer"] = create_agent_pane(ctx.session_name, "designer", ctx.agents)

    state["status"] = "designer_requested"
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "designer"
    write_state(ctx.files.state, state)
    send_prompt(ctx.panes["designer"], ctx.prompts["designer"])
    _mark(ctx, "plan_ready")
    return None


def handle_design_ready(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 2: design_ready -> plan_ready (coder handoff)."""
    kill_agent_pane(ctx.panes.get("designer"), ctx.session_name)
    ctx.panes["designer"] = None

    state.pop("needs_design", None)
    state["status"] = "plan_ready"
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "architect"
    write_state(ctx.files.state, state)

    _mark(ctx, "design_ready")
    ctx.handled.discard("plan_ready")
    return None


def handle_plan_ready_multi(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 3: plan_ready (multiple subplans) -> coders_requested."""
    for done_marker in ctx.files.feature_dir.glob("done_*"):
        if done_marker.is_file():
            done_marker.unlink()

    subplan_paths = split_plan_into_subplans(ctx.files.plan, ctx.files.feature_dir)
    subplan_count = len(subplan_paths)

    for subplan_index, subplan_path in enumerate(subplan_paths, start=1):
        pane_id = create_agent_pane(ctx.session_name, "coder", ctx.agents)
        ctx.coder_panes[subplan_index] = pane_id
        subplan_prompt = write_prompt_file(
            ctx.files.feature_dir,
            f"coder_prompt_{subplan_index}.txt",
            build_coder_subplan_prompt(
                ctx.files,
                subplan_path=subplan_path,
                subplan_index=subplan_index,
                state_target="implementation_done",
            ),
        )
        send_prompt(pane_id, subplan_prompt)

    state["status"] = "coders_requested"
    state["subplan_count"] = subplan_count
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "coder"
    write_state(ctx.files.state, state)
    _mark(ctx, "plan_ready")
    return None


def handle_plan_ready_single(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 4: plan_ready (single plan) -> coder_requested."""
    for done_marker in ctx.files.feature_dir.glob("done_*"):
        if done_marker.is_file():
            done_marker.unlink()

    if not tmux_pane_exists(ctx.panes["coder"]):
        ctx.panes["coder"] = create_agent_pane(ctx.session_name, "coder", ctx.agents)

    state["status"] = "coder_requested"
    state["subplan_count"] = 1
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "coder"
    write_state(ctx.files.state, state)
    send_prompt(ctx.panes["coder"], ctx.prompts["coder"])
    _mark(ctx, "plan_ready")
    return None


def handle_coders_done(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 5: coders_requested (all done) -> implementation_done."""
    for pane_id in ctx.coder_panes.values():
        kill_agent_pane(pane_id, ctx.session_name)
    ctx.coder_panes.clear()

    state["status"] = "implementation_done"
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "architect"
    write_state(ctx.files.state, state)
    return None


def handle_start_review(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 6: implementation_done -> review_requested."""
    update_state(
        ctx.files.state,
        "review_requested",
        updated_by="pipeline",
        active_role="architect",
    )
    send_prompt(ctx.panes["architect"], ctx.prompts["review"])
    _mark(ctx, "implementation_done")
    return None


def handle_review_fail(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 7: review_ready (verdict=fail) -> fix_requested."""
    for pane_id in ctx.coder_panes.values():
        kill_agent_pane(pane_id, ctx.session_name)
    ctx.coder_panes.clear()

    review_text = ctx.files.review.read_text(encoding="utf-8")
    review_iteration = int(state.get("review_iteration", 0))
    ctx.files.fix_request.write_text(review_text, encoding="utf-8")

    state["review_iteration"] = review_iteration + 1
    state["status"] = "fix_requested"
    state["subplan_count"] = 1
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "coder"
    write_state(ctx.files.state, state)

    if not tmux_pane_exists(ctx.panes["coder"]):
        ctx.panes["coder"] = create_agent_pane(ctx.session_name, "coder", ctx.agents)

    fix_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "fix_prompt.txt",
        build_fix_prompt(ctx.files, state_target="implementation_done"),
    )
    send_prompt(ctx.panes["coder"], fix_prompt)

    # Allow implementation_done and review_ready to re-fire in the next review iteration
    ctx.handled.discard("implementation_done")
    ctx.handled.discard("review_ready")
    return None


def handle_review_pass_docs(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 8: review_ready (verdict=pass, docs agent) -> docs_update_requested."""
    kill_agent_pane(ctx.panes["coder"], ctx.session_name)
    ctx.panes["coder"] = None

    review_text = ctx.files.review.read_text(encoding="utf-8")
    verdict = parse_review_verdict(review_text)
    if verdict is None:
        print(
            "Warning: parse_review_verdict returned None — treating as pass and requesting docs update"
        )

    update_state(
        ctx.files.state,
        "docs_update_requested",
        updated_by="pipeline",
        active_role="docs",
    )
    ctx.panes["docs"] = create_agent_pane(ctx.session_name, "docs", ctx.agents)
    docs_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "docs_prompt.txt",
        build_docs_prompt(ctx.files, state_target="docs_updated"),
    )
    send_prompt(ctx.panes["docs"], docs_prompt)
    _mark(ctx, "review_ready")
    return None


def handle_review_pass_no_docs(
    state: dict[str, Any], ctx: PipelineContext
) -> str | None:
    """Row 9: review_ready (verdict=pass, no docs) -> completion_pending."""
    kill_agent_pane(ctx.panes["coder"], ctx.session_name)
    ctx.panes["coder"] = None

    review_text = ctx.files.review.read_text(encoding="utf-8")
    verdict = parse_review_verdict(review_text)
    if verdict is None:
        print(
            "Warning: parse_review_verdict returned None — treating as pass and sending confirmation"
        )

    update_state(
        ctx.files.state,
        "completion_pending",
        updated_by="pipeline",
        active_role="architect",
    )
    send_prompt(ctx.panes["architect"], ctx.prompts["confirmation"])
    _mark(ctx, "review_ready")
    return None


def handle_docs_done(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 10: docs_updated -> completion_pending."""
    kill_agent_pane(ctx.panes["docs"], ctx.session_name)
    ctx.panes["docs"] = None

    update_state(
        ctx.files.state,
        "completion_pending",
        updated_by="pipeline",
        active_role="architect",
    )
    send_prompt(ctx.panes["architect"], ctx.prompts["confirmation"])
    _mark(ctx, "docs_updated")
    return None


def handle_changes_requested(
    state: dict[str, Any], ctx: PipelineContext
) -> str | None:
    """Row 11: changes_requested -> architect_requested (full reset)."""
    kill_agent_pane(ctx.panes["coder"], ctx.session_name)
    ctx.panes["coder"] = None
    kill_agent_pane(ctx.panes.get("docs"), ctx.session_name)
    ctx.panes["docs"] = None
    kill_agent_pane(ctx.panes.get("designer"), ctx.session_name)
    ctx.panes["designer"] = None
    for pane_id in ctx.coder_panes.values():
        kill_agent_pane(pane_id, ctx.session_name)
    ctx.coder_panes.clear()

    changes_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "changes_prompt.txt",
        build_change_prompt(ctx.files, state_target="plan_ready"),
    )
    send_prompt(ctx.panes["architect"], changes_prompt)

    state["status"] = "architect_requested"
    state["subplan_count"] = 0
    state["review_iteration"] = 0
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "architect"
    write_state(ctx.files.state, state)

    # Full reset — all transitions can fire again
    ctx.handled.clear()
    return None


def handle_completion_approved(
    state: dict[str, Any], ctx: PipelineContext
) -> str | None:
    """Row 12: completion_approved -> EXIT_SUCCESS."""
    commit_message = str(state.get("commit_message", "")).strip()
    raw_commit_files = state.get("commit_files", [])
    commit_files = (
        [str(path).strip() for path in raw_commit_files if str(path).strip()]
        if isinstance(raw_commit_files, list)
        else []
    )
    commit_hash = commit_changes(ctx.files.project_dir, commit_message, commit_files)
    if commit_hash is not None:
        print("Completion approved and commit created.")
        print(f"Commit message: {commit_message}")
        print(f"Commit hash: {commit_hash}")
        print("Committed files:")
        for file_path in commit_files:
            print(f"- {file_path}")
    else:
        print("Completion approved, but commit step failed or was skipped.")

    cleanup_feature_dir(ctx.files.feature_dir)
    return EXIT_SUCCESS


def handle_failed(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """Row 13: failed -> EXIT_FAILURE."""
    return EXIT_FAILURE
