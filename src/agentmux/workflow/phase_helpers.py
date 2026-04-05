from __future__ import annotations

from pathlib import Path

from ..sessions.state_store import now_iso, read_json_resilient, write_state
from .transitions import PipelineContext


def validate_last_event(value: str) -> None:
    """Validate that value is a known workflow event name.

    Raises ValueError for unknown event names to catch typos at write time.
    """
    from .event_catalog import VALID_LAST_EVENTS  # lazy import avoids circular deps

    if value not in VALID_LAST_EVENTS:
        raise ValueError(
            f"Unknown last_event: {value!r}. Valid values: {sorted(VALID_LAST_EVENTS)}"
        )


def send_to_role(
    ctx: PipelineContext,
    role: str,
    prompt_file: Path,
    *,
    display_label: str | None = None,
    prefix_command: str | None = None,
) -> None:
    ctx.runtime.send(
        role, prompt_file, display_label=display_label, prefix_command=prefix_command
    )


def write_phase(
    ctx: PipelineContext,
    state: dict,
    phase: str,
    last_event: str,
    **extra_fields: object,
) -> None:
    validate_last_event(last_event)
    state["phase"] = phase
    state["last_event"] = last_event
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state.update(extra_fields)
    write_state(ctx.files.state, state)
    ctx.entered_phase = None


def reset_markers(feature_dir: Path, pattern: str) -> None:
    for path in feature_dir.glob(pattern):
        if path.is_file():
            path.unlink()


def load_plan_meta(planning_dir: Path) -> dict[str, object]:
    return read_json_resilient(planning_dir / "plan_meta.json", {})


# =============================================================================
# NEW HELPER FUNCTIONS - Event-driven handler shared functionality
# =============================================================================


def dispatch_research_task(
    role: str,
    topic: str,
    state: dict,
    ctx: PipelineContext,
) -> tuple[dict, str | None]:
    """Dispatch a research task (code-researcher or web-researcher).

    Handles:
    - Checking if already dispatched
    - Removing stale done markers
    - Building and writing the prompt
    - Spawning the task

    Args:
        role: Either "code-researcher" or "web-researcher"
        topic: The research topic (e.g., "auth", "api")
        state: Current state dict (read-only)
        ctx: Pipeline context

    Returns:
        Tuple of (state_updates, None) - never transitions phase
    """
    from .prompts import (
        build_code_researcher_prompt,
        build_web_researcher_prompt,
        write_prompt_file,
    )

    # Determine state key and prefix
    is_code = role == "code-researcher"
    tasks_key = "research_tasks" if is_code else "web_research_tasks"
    prefix = "code-" if is_code else "web-"

    # Check if already dispatched
    tasks = dict(state.get(tasks_key, {}))
    if topic in tasks:
        return {}, None

    # Remove stale done marker if exists
    done_marker = ctx.files.research_dir / f"{prefix}{topic}" / "done"
    if done_marker.exists():
        done_marker.unlink()

    # Build and write prompt
    research_dir = ctx.files.research_dir / f"{prefix}{topic}"
    prompt_builder = (
        build_code_researcher_prompt if is_code else build_web_researcher_prompt
    )
    write_prompt_file(
        ctx.files.feature_dir,
        ctx.files.relative_path(research_dir / "prompt.md"),
        prompt_builder(topic, ctx.files),
    )

    # Spawn task
    ctx.runtime.spawn_task(role, topic, research_dir)

    # Update state
    tasks[topic] = "dispatched"
    return {tasks_key: tasks}, None


def notify_research_complete(
    role: str,
    topic: str,
    state: dict,
    ctx: PipelineContext,
    notify_target: str,
) -> tuple[dict, str | None]:
    """Notify that a research task is complete.

    Handles:
    - Finishing the task in runtime
    - Notifying the target role with summary path
    - Updating state

    Args:
        role: Either "code-researcher" or "web-researcher"
        topic: The research topic
        state: Current state dict (read-only)
        ctx: Pipeline context
        notify_target: Role to notify (e.g., "architect", "product-manager")

    Returns:
        Tuple of (state_updates, None) - never transitions phase
    """
    # Finish task
    ctx.runtime.finish_task(role, topic)

    # Notify target
    is_code = role == "code-researcher"
    prefix = "code-" if is_code else "web-"
    role_name = "Code-research" if is_code else "Web research"

    summary_path = ctx.files.relative_path(
        ctx.files.research_dir / f"{prefix}{topic}" / "summary.md"
    )
    ctx.runtime.notify(
        notify_target,
        f"{role_name} on '{topic}' is complete. "
        f"Read {summary_path} and continue from there.",
    )

    # Update state
    tasks_key = "research_tasks" if is_code else "web_research_tasks"
    tasks = dict(state.get(tasks_key, {}))
    tasks[topic] = "done"
    return {tasks_key: tasks}, None


def apply_role_preferences(ctx: PipelineContext, role: str) -> None:
    """Apply approved preferences for a role if they exist.

    Args:
        ctx: Pipeline context with files
        role: Role name (e.g., "architect", "product-manager", "reviewer")
    """
    from .preference_memory import (
        apply_preference_proposal,
        load_preference_proposal,
        proposal_artifact_for_source,
    )

    proposal_path = proposal_artifact_for_source(ctx.files, role)
    proposal = load_preference_proposal(proposal_path)
    if proposal:
        apply_preference_proposal(ctx.files.project_dir, proposal)


def select_reviewer_type(plan_meta: dict) -> str:
    """Select the appropriate reviewer type based on plan_meta review_strategy.

    Args:
        plan_meta: The plan_meta dictionary from 02_planning/plan_meta.json

    Returns:
        One of "logic" | "quality" | "expert"

    Rules:
        - Missing review_strategy -> "logic" (backward compat default)
        - low severity -> "quality"
        - medium severity + no security/performance in focus -> "logic"
        - medium severity + security OR performance in focus -> "expert"
        - high severity + no security/performance in focus -> "logic"
        - high severity + security OR performance in focus -> "expert"
    """
    review_strategy = plan_meta.get("review_strategy")
    if not review_strategy:
        return "logic"

    severity = review_strategy.get("severity", "").lower()
    focus = review_strategy.get("focus", [])

    # Normalize focus to lowercase strings for comparison
    focus_lower = set()
    for item in focus:
        if isinstance(item, str):
            focus_lower.add(item.lower())

    has_security_focus = "security" in focus_lower
    has_performance_focus = "performance" in focus_lower
    needs_expert = has_security_focus or has_performance_focus

    if severity == "low":
        return "quality"

    if severity == "medium":
        return "expert" if needs_expert else "logic"

    if severity == "high":
        return "expert" if needs_expert else "logic"

    # Default fallback for unknown severity
    return "logic"
