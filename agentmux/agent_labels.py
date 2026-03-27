from __future__ import annotations

import json
import re
from pathlib import Path

from .sessions.state_store import feature_slug_from_dir
from .shared.models import SESSION_DIR_NAMES
from .workflow.execution_plan import load_execution_plan
from .workflow.plan_parser import read_subplan_title

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
        execution_plan = None
    if execution_plan is not None:
        target = f"plan_{index}.md"
        for group in execution_plan.groups:
            for plan in group.plans:
                if plan.file == target:
                    return plan.name

    return read_subplan_title(planning_dir / f"plan_{index}.md")


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


def role_display_label(
    feature_dir: Path,
    role: str,
    *,
    task_id: int | str | None = None,
    state: dict | None = None,
) -> str:
    current_state = state if state is not None else _load_state_safe(feature_dir)

    if role == "architect":
        return format_agent_label(role, "planning")
    if role == "product-manager":
        return format_agent_label(role, "analysis")
    if role == "designer":
        return format_agent_label(role, design_subject(feature_dir))
    if role == "coder":
        return format_agent_label(role, _coder_detail(feature_dir, current_state, task_id))
    if role == "reviewer":
        return format_agent_label(role, f"iteration {_review_iteration(current_state) + 1}")
    if role in {"code-researcher", "web-researcher"} and task_id is not None:
        return format_agent_label(role, str(task_id))
    if task_id is not None:
        return format_agent_label(role, str(task_id))
    return format_agent_label(role)
