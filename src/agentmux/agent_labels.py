from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from .sessions.state_store import feature_slug_from_dir
from .shared.models import SESSION_DIR_NAMES
from .workflow.execution_plan import load_execution_plan

_PLAN_ID_RE = re.compile(r"^plan_(\d+)(?:\.md)?$")


def format_agent_label(role: str, detail: str | None = None) -> str:
    detail_text = (detail or "").strip()
    if detail_text:
        return f"[{role}] {detail_text}"
    return f"[{role}]"


def _load_state_safe(feature_dir: Path) -> dict:
    state_path = feature_dir / "state.json"
    try:
        text = state_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _review_iteration(state: dict) -> int:
    try:
        return max(0, int(state.get("review_iteration", 0)))
    except (TypeError, ValueError):
        return 0


def design_subject(feature_dir: Path) -> str:
    slug = feature_slug_from_dir(feature_dir).replace("-", " ").strip()
    return slug or "design"


def plan_name_for_subplan(planning_dir: Path, subplan_index: int | str) -> str | None:
    try:
        index = int(subplan_index)
    except (TypeError, ValueError):
        return None

    try:
        execution_plan = load_execution_plan(planning_dir)
    except RuntimeError:
        return None
    target = f"plan_{index}.md"
    for group in execution_plan.groups:
        for plan in group.plans:
            if plan.file == target:
                return plan.name
    return None


def plan_name_for_plan_id(planning_dir: Path, plan_id: str) -> str | None:
    match = _PLAN_ID_RE.match(str(plan_id).strip())
    if match is None:
        return None
    return plan_name_for_subplan(planning_dir, int(match.group(1)))


def _coder_detail(feature_dir: Path, state: dict, task_id: int | str | None) -> str:
    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    phase = str(state.get("phase", "")).strip()
    review_iteration = _review_iteration(state)

    if phase == "fixing":
        return f"fix {max(1, review_iteration)}"

    if task_id is not None:
        return plan_name_for_subplan(planning_dir, task_id) or f"plan {task_id}"

    active_plan_ids = [
        str(value).strip()
        for value in list(state.get("implementation_active_plan_ids", []))
        if str(value).strip()
    ]
    if active_plan_ids:
        first_plan_name = plan_name_for_plan_id(planning_dir, active_plan_ids[0])
        if first_plan_name:
            return first_plan_name
        if len(active_plan_ids) == 1 and _PLAN_ID_RE.match(active_plan_ids[0]):
            return "implementation"
        return active_plan_ids[0]

    return "implementation"


DetailFn = Callable[["Path", dict, "int | str | None"], "str | None"]

ROLE_DETAIL_DISPATCH: dict[str, DetailFn] = {
    "architect": lambda fd, s, t: "planning",
    "product-manager": lambda fd, s, t: "analysis",
    "planner": lambda fd, s, t: "planning",
    "designer": lambda fd, s, t: design_subject(fd),
    "coder": lambda fd, s, t: _coder_detail(fd, s, t),
    "reviewer": lambda fd, s, t: f"iteration {_review_iteration(s) + 1}",
    "reviewer_logic": lambda fd, s, t: "logic",
    "reviewer_quality": lambda fd, s, t: "quality",
    "reviewer_expert": lambda fd, s, t: "expert",
    "code-researcher": lambda fd, s, t: str(t) if t is not None else None,
    "web-researcher": lambda fd, s, t: str(t) if t is not None else None,
}


def role_display_label(
    feature_dir: Path,
    role: str,
    *,
    task_id: int | str | None = None,
    state: dict | None = None,
) -> str:
    current_state = state if state is not None else _load_state_safe(feature_dir)
    detail_fn = ROLE_DETAIL_DISPATCH.get(role)
    if detail_fn is not None:
        detail = detail_fn(feature_dir, current_state, task_id)
    elif task_id is not None:
        detail = str(task_id)
    else:
        detail = None
    return format_agent_label(role, detail)
