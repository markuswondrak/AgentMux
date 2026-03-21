from __future__ import annotations

import json
from typing import Any

from .plan_parser import split_plan_into_subplans
from .prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_coder_prompt,
    build_coder_subplan_prompt,
    build_confirmation_prompt,
    build_designer_prompt,
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
    _ensure_agent_pane,
    create_agent_pane,
    kill_agent_pane,
    park_agent_pane,
    send_prompt,
    show_agent_pane,
)
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext


def _mark(ctx: PipelineContext, status: str) -> None:
    """Mark a status as handled so it won't re-fire."""
    ctx.handled.add(status)


def _send(ctx: PipelineContext, role: str, prompt_file) -> None:
    """Send a prompt to an agent, creating the pane lazily if needed."""
    send_prompt(
        ctx.panes.get(role),
        prompt_file,
        ctx.session_name,
        role=role,
        agents=ctx.agents,
        panes=ctx.panes,
    )


def _ensure_pane(ctx: PipelineContext, role: str) -> str | None:
    """Ensure an agent pane exists (create lazily if needed). Returns pane ID."""
    return _ensure_agent_pane(ctx.session_name, role, ctx.agents, ctx.panes)


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
    """plan_ready (needs design) -> designer_requested."""
    state["status"] = "designer_requested"
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "designer"
    write_state(ctx.files.state, state)
    designer_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "designer_prompt.md",
        build_designer_prompt(ctx.files, state_target="design_ready"),
    )
    _send(ctx, "designer", designer_prompt)
    _mark(ctx, "plan_ready")
    return None


def handle_design_ready(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """design_ready -> plan_ready (coder handoff)."""
    park_agent_pane(ctx.panes.get("designer"), ctx.session_name)

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
    """plan_ready (multiple subplans) -> coders_requested."""
    for done_marker in ctx.files.feature_dir.glob("done_*"):
        if done_marker.is_file():
            done_marker.unlink()

    subplan_paths = split_plan_into_subplans(ctx.files.plan, ctx.files.feature_dir)
    subplan_count = len(subplan_paths)

    for subplan_index, subplan_path in enumerate(subplan_paths, start=1):
        if subplan_index == 1:
            # Use the primary coder pane (create lazily if needed)
            pane_id = _ensure_pane(ctx, "coder")
            # First pane: exclusive=True to park architect etc.
            show_agent_pane(pane_id, ctx.session_name, exclusive=True)
        else:
            pane_id = create_agent_pane(ctx.session_name, "coder", ctx.agents)
            # Additional panes: exclusive=False to stack vertically
            show_agent_pane(pane_id, ctx.session_name, exclusive=False)
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
    """plan_ready (single plan) -> coder_requested."""
    for done_marker in ctx.files.feature_dir.glob("done_*"):
        if done_marker.is_file():
            done_marker.unlink()

    state["status"] = "coder_requested"
    state["subplan_count"] = 1
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "coder"
    write_state(ctx.files.state, state)
    coder_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "coder_prompt.md",
        build_coder_prompt(ctx.files, state_target="implementation_done"),
    )
    _send(ctx, "coder", coder_prompt)
    _mark(ctx, "plan_ready")
    return None


def handle_coders_done(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """coders_requested (all done) -> implementation_done."""
    # Kill extra parallel coder panes (they were dynamically created)
    for idx, pane_id in ctx.coder_panes.items():
        if pane_id != ctx.panes.get("coder"):
            kill_agent_pane(pane_id, ctx.session_name)
    # Park the primary coder pane
    park_agent_pane(ctx.panes.get("coder"), ctx.session_name)
    ctx.coder_panes.clear()

    state["status"] = "implementation_done"
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state["active_role"] = "architect"
    write_state(ctx.files.state, state)
    return None


def handle_start_review(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """implementation_done -> review_requested."""
    update_state(
        ctx.files.state,
        "review_requested",
        updated_by="pipeline",
        active_role="architect",
    )
    review_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "review_prompt.md",
        build_architect_prompt(ctx.files, state_target="review_ready", is_review=True),
    )
    _send(ctx, "architect", review_prompt)
    _mark(ctx, "implementation_done")
    return None


def handle_review_fail(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """review_ready (verdict=fail) -> fix_requested."""
    # Kill any extra parallel coder panes
    for pane_id in ctx.coder_panes.values():
        if pane_id != ctx.panes.get("coder"):
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

    fix_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "fix_prompt.txt",
        build_fix_prompt(ctx.files, state_target="implementation_done"),
    )
    _send(ctx, "coder", fix_prompt)

    # Allow implementation_done and review_ready to re-fire in the next review iteration
    ctx.handled.discard("implementation_done")
    ctx.handled.discard("review_ready")
    return None


def handle_review_pass_docs(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """review_ready (verdict=pass, docs agent) -> docs_update_requested."""
    park_agent_pane(ctx.panes.get("coder"), ctx.session_name)

    status = str(state.get("status", ""))
    if status == "review_ready":
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
    docs_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "docs_prompt.txt",
        build_docs_prompt(ctx.files, state_target="docs_updated"),
    )
    _send(ctx, "docs", docs_prompt)
    _mark(ctx, status)
    return None


def handle_review_pass_no_docs(
    state: dict[str, Any], ctx: PipelineContext
) -> str | None:
    """review_ready (verdict=pass, no docs) -> completion_pending."""
    park_agent_pane(ctx.panes.get("coder"), ctx.session_name)

    status = str(state.get("status", ""))
    if status == "review_ready":
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
    confirmation_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "confirmation_prompt.md",
        build_confirmation_prompt(
            ctx.files,
            approved_target="completion_approved",
            changes_target="changes_requested",
        ),
    )
    _send(ctx, "architect", confirmation_prompt)
    _mark(ctx, status)
    return None


def handle_docs_done(state: dict[str, Any], ctx: PipelineContext) -> str | None:
    """docs_updated -> completion_pending."""
    park_agent_pane(ctx.panes.get("docs"), ctx.session_name)

    update_state(
        ctx.files.state,
        "completion_pending",
        updated_by="pipeline",
        active_role="architect",
    )
    confirmation_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "confirmation_prompt.md",
        build_confirmation_prompt(
            ctx.files,
            approved_target="completion_approved",
            changes_target="changes_requested",
        ),
    )
    _send(ctx, "architect", confirmation_prompt)
    _mark(ctx, "docs_updated")
    return None


def handle_changes_requested(
    state: dict[str, Any], ctx: PipelineContext
) -> str | None:
    """changes_requested -> architect_requested (full reset)."""
    park_agent_pane(ctx.panes.get("coder"), ctx.session_name)
    park_agent_pane(ctx.panes.get("docs"), ctx.session_name)
    park_agent_pane(ctx.panes.get("designer"), ctx.session_name)
    # Kill any extra parallel coder panes
    for pane_id in ctx.coder_panes.values():
        if pane_id != ctx.panes.get("coder"):
            kill_agent_pane(pane_id, ctx.session_name)
    ctx.coder_panes.clear()

    changes_prompt = write_prompt_file(
        ctx.files.feature_dir,
        "changes_prompt.txt",
        build_change_prompt(ctx.files, state_target="plan_ready"),
    )
    _send(ctx, "architect", changes_prompt)

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
    """completion_approved -> EXIT_SUCCESS."""
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
    """failed -> EXIT_FAILURE."""
    return EXIT_FAILURE
