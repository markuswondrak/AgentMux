from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionProgress:
    total: int
    completed: int
    active_index: int | None
    active_group: str
    active_mode: str  # "serial" | "parallel" | ""
    active_plan_ids: list[str]
    completed_group_ids: list[str]
    queued_group_ids: list[str]


def _extract_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _extract_str(raw: object) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _extract_str_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        item = raw.strip()
        return [item] if item else []
    if isinstance(raw, list):
        values: list[str] = []
        for item in raw:
            text = _extract_str(item)
            if text:
                values.append(text)
        return values
    return []


def _first_present(mapping: dict[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _first_present_with_key(
    mapping: dict[str, object], keys: tuple[str, ...]
) -> tuple[str | None, object | None]:
    for key in keys:
        if key in mapping:
            return key, mapping[key]
    return None, None


def _normalize_group_mode(raw: object) -> str:
    mode = _extract_str(raw).lower()
    if mode in {"serial", "parallel"}:
        return mode
    return ""


def _normalize_groups(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []

    groups: list[dict[str, object]] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            group_id = _extract_str(
                _first_present(
                    item,
                    (
                        "id",
                        "group_id",
                        "name",
                        "label",
                    ),
                )
            )
            if not group_id:
                group_id = f"g{i}"
            groups.append(
                {
                    "id": group_id,
                    "mode": _normalize_group_mode(
                        _first_present(item, ("mode", "execution_mode", "group_mode"))
                    ),
                    "plan_ids": _extract_str_list(
                        _first_present(
                            item, ("plan_ids", "plans", "plan_files", "plan_refs")
                        )
                    ),
                }
            )
            continue

        label = _extract_str(item)
        groups.append({"id": label or f"g{i}", "mode": "", "plan_ids": []})
    return groups


def _normalize_active_index(raw: object, *, total: int) -> int | None:
    parsed = _extract_int(raw)
    if parsed is None:
        return None
    if 0 <= parsed < total:
        return parsed
    if 1 <= parsed <= total:
        return parsed - 1
    return None


def parse_execution_progress(state: dict[str, object]) -> ExecutionProgress | None:
    root_candidates: list[dict[str, object]] = []
    for key in (
        "execution_progress",
        "implementing_progress",
        "implementation_progress",
        "staged_execution",
    ):
        value = state.get(key)
        if isinstance(value, dict):
            root_candidates.append(value)
    root_candidates.append(state)

    total_keys = (
        "total_groups",
        "group_total",
        "groups_total",
        "execution_group_total",
        "implementing_total_groups",
        "implementation_group_total",
    )
    completed_keys = (
        "completed_groups",
        "completed_group_count",
        "groups_completed",
        "execution_groups_completed",
        "implementing_completed_groups",
        "implementation_completed_groups",
        "implementation_completed_group_ids",
    )
    active_index_keys = (
        "active_group_index",
        "current_group_index",
        "group_index",
        "execution_group_index",
        "implementing_active_group_index",
        "implementation_group_index",
    )
    active_mode_keys = (
        "active_group_mode",
        "current_group_mode",
        "group_mode",
        "execution_group_mode",
        "implementing_active_group_mode",
        "implementation_group_mode",
    )
    active_plan_keys = (
        "active_plan_ids",
        "current_plan_ids",
        "execution_active_plan_ids",
        "implementing_active_plan_ids",
        "implementation_active_plan_ids",
    )
    active_group_keys = (
        "active_group_id",
        "current_group_id",
        "group_id",
        "execution_group_id",
    )
    groups_keys = (
        "groups",
        "execution_groups",
        "implementation_groups",
        "schedule",
        "execution_schedule",
    )
    signal_keys = (
        total_keys
        + completed_keys
        + active_index_keys
        + active_mode_keys
        + active_plan_keys
        + groups_keys
    )

    for raw in root_candidates:
        if not any(key in raw for key in signal_keys):
            continue

        groups = _normalize_groups(_first_present(raw, groups_keys))
        total = _extract_int(_first_present(raw, total_keys))
        if total is None:
            total = len(groups)
        if total is None or total <= 0:
            continue

        active_index_key, active_index_raw = _first_present_with_key(
            raw, active_index_keys
        )
        if active_index_key == "implementation_group_index":
            parsed_active_index = _extract_int(active_index_raw)
            if parsed_active_index is None:
                active_index = None
            elif 1 <= parsed_active_index <= total:
                active_index = parsed_active_index - 1
            elif parsed_active_index == 0 and total > 0:
                active_index = 0
            else:
                active_index = None
        else:
            active_index = _normalize_active_index(active_index_raw, total=total)
        completed_raw = _first_present(raw, completed_keys)
        if isinstance(completed_raw, list):
            completed = len(completed_raw)
        else:
            completed = _extract_int(completed_raw)
        if completed is None and active_index is not None:
            completed = active_index
        if completed is None:
            completed = 0
        completed = max(0, min(total, completed))

        if active_index is None and completed < total:
            active_index = completed
        if active_index is not None and not (0 <= active_index < total):
            active_index = None

        synthetic_ids = [f"g{i}" for i in range(1, total + 1)]
        group_ids = [
            str(g.get("id", f"g{i + 1}")).strip() or f"g{i + 1}"
            for i, g in enumerate(groups)
        ]
        if len(group_ids) < total:
            group_ids.extend(synthetic_ids[len(group_ids) : total])
        elif len(group_ids) > total:
            group_ids = group_ids[:total]

        active_group = _extract_str(_first_present(raw, active_group_keys))
        if (
            not active_group
            and active_index is not None
            and active_index < len(group_ids)
        ):
            active_group = group_ids[active_index]
        elif not active_group and active_index is not None:
            active_group = f"g{active_index + 1}"

        active_mode = _normalize_group_mode(_first_present(raw, active_mode_keys))
        if not active_mode and active_index is not None and active_index < len(groups):
            active_mode = _normalize_group_mode(groups[active_index].get("mode"))

        active_plan_ids = _extract_str_list(_first_present(raw, active_plan_keys))
        if (
            not active_plan_ids
            and active_index is not None
            and active_index < len(groups)
        ):
            active_plan_ids = _extract_str_list(groups[active_index].get("plan_ids"))

        completed_group_ids: list[str] = []
        queued_group_ids: list[str] = []
        if active_index is not None:
            completed_group_ids = group_ids[:active_index]
            queued_group_ids = group_ids[active_index + 1 :]
        else:
            completed_group_ids = group_ids[:completed]
            queued_group_ids = group_ids[completed:]

        return ExecutionProgress(
            total=total,
            completed=completed,
            active_index=active_index,
            active_group=active_group,
            active_mode=active_mode,
            active_plan_ids=active_plan_ids,
            completed_group_ids=completed_group_ids,
            queued_group_ids=queued_group_ids,
        )

    return None
