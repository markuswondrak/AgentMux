from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..sessions.state_store import now_iso, write_state
from .transitions import PipelineContext

if TYPE_CHECKING:
    from .event_router import WorkflowEvent


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
    import yaml

    path = planning_dir / "execution_plan.yaml"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    meta_keys = {"needs_design", "needs_docs", "doc_files", "review_strategy"}
    return {k: v for k, v in data.items() if k in meta_keys}


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


def handle_research_request(
    role: str,
    event: WorkflowEvent,
    state: dict,
    ctx: PipelineContext,
) -> tuple[dict, str | None]:
    """Extract payload, write request.md, and dispatch a research task.

    Shared by all handlers that respond to research_code_req / research_web_req
    tool events. The only difference per call site is the role string.

    Args:
        role: "code-researcher" or "web-researcher"
        event: The incoming WorkflowEvent (payload["payload"] is the MCP payload)
        state: Current state dict (read-only)
        ctx: Pipeline context

    Returns:
        Tuple of (state_updates, None) — never transitions phase
    """
    payload = event.payload.get("payload", {})
    topic = payload.get("topic", "")
    if not topic:
        return {}, None

    prefix = "code-" if role == "code-researcher" else "web-"
    req_dir = ctx.files.research_dir / f"{prefix}{topic}"
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

    return dispatch_research_task(role, topic, state, ctx)


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


def handle_research_done(
    event: WorkflowEvent,
    state: dict,
    ctx: PipelineContext,
    notify_target: str,
) -> tuple[dict, str | None]:
    """Handle research completion via tool event.

    Shared by all handlers that respond to research_done tool events.
    The only difference per call site is the notify_target string.

    Args:
        event: The incoming WorkflowEvent (payload["payload"] is the MCP payload)
        state: Current state dict (read-only)
        ctx: Pipeline context
        notify_target: Role to notify (e.g., "architect", "planner", "product-manager")

    Returns:
        Tuple of (state_updates, None) — never transitions phase
    """
    payload = event.payload.get("payload", {})
    topic = payload.get("topic", "")
    role = research_role_from_payload(payload)
    if not topic or role is None:
        return {}, None

    return notify_research_complete(role, topic, state, ctx, notify_target)


def research_role_from_payload(payload: dict) -> str | None:
    """Map research-done payloads to the corresponding researcher role."""
    role_type = str(payload.get("role_type") or payload.get("type") or "").strip()
    if role_type == "code":
        return "code-researcher"
    if role_type == "web":
        return "web-researcher"
    return None


def select_reviewer_type(plan_meta: dict) -> str:
    """Select the appropriate reviewer type based on plan_meta review_strategy.

    Args:
        plan_meta: The plan_meta dictionary from 02_planning/execution_plan.yaml

    Returns:
        One of "logic" | "quality" | "expert"

    Rules:
        - Missing review_strategy -> "logic" (default)
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
