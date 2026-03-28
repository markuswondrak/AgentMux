from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_PLAN_FILE_RE = re.compile(r"^plan_\d+\.md$")
_GROUP_MODES = {"serial", "parallel"}


@dataclass(frozen=True)
class ExecutionPlanRef:
    file: str
    name: str | None = None


@dataclass(frozen=True)
class ExecutionGroup:
    group_id: str
    mode: str
    plans: list[ExecutionPlanRef]


@dataclass(frozen=True)
class ExecutionPlan:
    version: int
    groups: list[ExecutionGroup]


def _error(path: Path, message: str) -> RuntimeError:
    return RuntimeError(f"{path.name}: {message}")


def load_execution_plan(planning_dir: Path) -> ExecutionPlan:
    path = planning_dir / "execution_plan.json"
    if not path.is_file():
        raise _error(path, "is required.")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _error(path, "must contain valid JSON.") from exc

    if not isinstance(payload, dict):
        raise _error(path, "must be a JSON object.")

    version = payload.get("version")
    if version != 1:
        raise _error(path, "version must be 1.")

    groups_raw = payload.get("groups")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise _error(path, "groups must be a non-empty list.")

    groups: list[ExecutionGroup] = []
    seen_group_ids: set[str] = set()
    seen_plan_refs: set[str] = set()

    for index, group_raw in enumerate(groups_raw, start=1):
        if not isinstance(group_raw, dict):
            raise _error(path, f"groups[{index}] must be an object.")

        group_id_raw = group_raw.get("group_id")
        if not isinstance(group_id_raw, str) or not group_id_raw.strip():
            raise _error(path, f"groups[{index}].group_id must be a non-empty string.")
        group_id = group_id_raw.strip()
        if group_id in seen_group_ids:
            raise _error(path, f"groups[{index}].group_id has duplicate value '{group_id}'.")
        seen_group_ids.add(group_id)

        mode_raw = group_raw.get("mode")
        if not isinstance(mode_raw, str) or mode_raw not in _GROUP_MODES:
            raise _error(path, f"groups[{index}].mode must be one of: serial, parallel.")

        plans_raw = group_raw.get("plans")
        if not isinstance(plans_raw, list) or not plans_raw:
            raise _error(path, f"groups[{index}].plans must be a non-empty list.")

        plans: list[ExecutionPlanRef] = []
        for plan_index, plan_raw in enumerate(plans_raw, start=1):
            if not isinstance(plan_raw, dict):
                raise _error(path, f"groups[{index}].plans[{plan_index}] must be an object.")
            plan_file_raw = plan_raw.get("file")
            if not isinstance(plan_file_raw, str) or not plan_file_raw.strip():
                raise _error(path, f"groups[{index}].plans[{plan_index}].file must be a non-empty string.")
            plan_name_raw = plan_raw.get("name")
            if not isinstance(plan_name_raw, str) or not plan_name_raw.strip():
                raise _error(path, f"groups[{index}].plans[{plan_index}].name must be a non-empty string.")
            plan_ref = plan_file_raw.strip()
            plan_name = plan_name_raw.strip()
            if not _PLAN_FILE_RE.match(plan_ref):
                raise _error(
                    path,
                    f"groups[{index}].plans[{plan_index}] must match 'plan_<N>.md' and stay in 02_planning/.",
                )
            if plan_ref in seen_plan_refs:
                raise _error(path, f"groups[{index}].plans[{plan_index}] duplicates plan '{plan_ref}'.")
            plan_path = planning_dir / plan_ref
            if not plan_path.is_file():
                raise _error(path, f"groups[{index}].plans[{plan_index}] references missing file '{plan_ref}'.")
            seen_plan_refs.add(plan_ref)
            plans.append(ExecutionPlanRef(file=plan_ref, name=plan_name))

        groups.append(ExecutionGroup(group_id=group_id, mode=mode_raw, plans=plans))

    return ExecutionPlan(version=version, groups=groups)
