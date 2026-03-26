from __future__ import annotations

import os
import re
import textwrap
import time
from pathlib import Path

from .state_reader import (
    MonitorLogEntry,
    OPTIONAL_PHASES,
    PIPELINE_STATES,
    SESSION_DIR_NAMES,
    format_event,
    get_role_labels,
    get_role_states,
    load_state,
    read_feature_request,
    read_monitor_log_entries,
    trim_model,
)

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
WHITE = "\033[97m"

MONITOR_HEADER_LOGO = [
    (CYAN, "╭───────────╮"),
    (CYAN, "│ ▄▀█ █▀▄▀█ │"),
    (MAGENTA, "│ █▀█ █ ▀ █ │"),
    (MAGENTA, "╰───────────╯"),
]

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def get_terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 40, 24


def _vlen(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _truncate_text(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _separator(width: int) -> str:
    return f"{DIM}{'─' * max(1, width)}{RESET}"


def _section_title(label: str) -> str:
    return f" {BOLD}{label}{RESET}"


def _compose_line(
    width: int,
    *,
    prefix_plain: str = "",
    prefix_rendered: str = "",
    left_plain: str = "",
    left_rendered: str = "",
    right_plain: str = "",
    right_rendered: str = "",
) -> str:
    prefix_rendered = prefix_rendered or prefix_plain
    left_rendered = left_rendered or left_plain
    right_rendered = right_rendered or right_plain

    if width <= 0:
        return ""

    available = max(0, width - len(prefix_plain))
    if right_plain:
        min_gap = 1
        left_max = max(0, available - len(right_plain) - min_gap)
        left_plain = _truncate_text(left_plain, left_max)
        if _vlen(left_rendered) > len(left_plain):
            left_rendered = left_plain
        gap = available - len(left_plain) - len(right_plain)
        if gap < min_gap:
            right_max = max(0, available - len(left_plain) - min_gap)
            right_plain = _truncate_text(right_plain, right_max)
            if _vlen(right_rendered) > len(right_plain):
                right_rendered = right_plain
            gap = max(min_gap, available - len(left_plain) - len(right_plain))
        return f"{prefix_rendered}{left_rendered}{' ' * gap}{right_rendered}"

    left_plain = _truncate_text(left_plain, available)
    if _vlen(left_rendered) > len(left_plain):
        left_rendered = left_plain
    return f"{prefix_rendered}{left_rendered}"


def _spinner_frame() -> str:
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    return frames[int(time.time() * 8) % len(frames)]


def _wrap_feature_lines(text: str, width: int, *, max_lines: int = 4) -> list[str]:
    if width <= 0:
        return [""] * max_lines
    clean = " ".join(text.split())
    if not clean:
        return [""] * max_lines
    wrapped = textwrap.wrap(clean, width=width, break_long_words=True, break_on_hyphens=False)
    if len(wrapped) > max_lines:
        head = wrapped[: max_lines - 1]
        tail = " ".join(wrapped[max_lines - 1 :])
        wrapped = head + [textwrap.shorten(tail, width=width, placeholder="…")]
    while len(wrapped) < max_lines:
        wrapped.append("")
    return wrapped[:max_lines]


def _render_feature_header(width: int, state_path: Path) -> list[str]:
    feature_request = read_feature_request(state_path)
    logo_width = max(_vlen(row) for _, row in MONITOR_HEADER_LOGO)
    gap = 2
    text_width = width - logo_width - gap

    if text_width >= 10:
        feature_lines = _wrap_feature_lines(feature_request, text_width, max_lines=len(MONITOR_HEADER_LOGO))
        rows: list[str] = []
        for (color, logo_row), feature_line in zip(MONITOR_HEADER_LOGO, feature_lines):
            padded_logo = logo_row + (" " * max(0, logo_width - _vlen(logo_row)))
            logo_text = f"{BOLD}{color}{padded_logo}{RESET}"
            rows.append(f"{logo_text}{' ' * gap}{feature_line}" if feature_line else logo_text)
        return rows

    if width >= logo_width:
        rows = [f"{BOLD}{color}{logo_row}{RESET}" for color, logo_row in MONITOR_HEADER_LOGO]
        if feature_request:
            rows.extend(line for line in _wrap_feature_lines(feature_request, width, max_lines=2) if line)
        return rows

    if feature_request:
        return [line for line in _wrap_feature_lines(feature_request, max(1, width), max_lines=2) if line]
    return []


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
                        _first_present(item, ("plan_ids", "plans", "plan_files", "plan_refs"))
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


def _extract_execution_progress(state: dict[str, object]) -> dict[str, object] | None:
    root_candidates: list[dict[str, object]] = []
    for key in ("execution_progress", "implementing_progress", "implementation_progress", "staged_execution"):
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
    groups_keys = ("groups", "execution_groups", "implementation_groups", "schedule", "execution_schedule")
    signal_keys = total_keys + completed_keys + active_index_keys + active_mode_keys + active_plan_keys + groups_keys

    for raw in root_candidates:
        if not any(key in raw for key in signal_keys):
            continue

        groups = _normalize_groups(_first_present(raw, groups_keys))
        total = _extract_int(_first_present(raw, total_keys))
        if total is None:
            total = len(groups)
        if total is None or total <= 0:
            continue

        active_index_key, active_index_raw = _first_present_with_key(raw, active_index_keys)
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
        group_ids = [str(g.get("id", f"g{i + 1}")).strip() or f"g{i + 1}" for i, g in enumerate(groups)]
        if len(group_ids) < total:
            group_ids.extend(synthetic_ids[len(group_ids) : total])
        elif len(group_ids) > total:
            group_ids = group_ids[:total]

        active_group = _extract_str(_first_present(raw, active_group_keys))
        if not active_group and active_index is not None and active_index < len(group_ids):
            active_group = group_ids[active_index]
        elif not active_group and active_index is not None:
            active_group = f"g{active_index + 1}"

        active_mode = _normalize_group_mode(_first_present(raw, active_mode_keys))
        if not active_mode and active_index is not None and active_index < len(groups):
            active_mode = _normalize_group_mode(groups[active_index].get("mode"))

        active_plan_ids = _extract_str_list(_first_present(raw, active_plan_keys))
        if not active_plan_ids and active_index is not None and active_index < len(groups):
            active_plan_ids = _extract_str_list(groups[active_index].get("plan_ids"))

        completed_group_ids: list[str] = []
        queued_group_ids: list[str] = []
        if active_index is not None:
            completed_group_ids = group_ids[:active_index]
            queued_group_ids = group_ids[active_index + 1 :]
        else:
            completed_group_ids = group_ids[:completed]
            queued_group_ids = group_ids[completed:]

        return {
            "total": total,
            "completed": completed,
            "active_index": active_index,
            "active_group": active_group,
            "active_mode": active_mode,
            "active_plan_ids": active_plan_ids,
            "completed_group_ids": completed_group_ids,
            "queued_group_ids": queued_group_ids,
        }

    return None


def _format_plan_summary(plan_ids: list[str]) -> str:
    if not plan_ids:
        return ""
    if len(plan_ids) == 1:
        return plan_ids[0]
    if len(plan_ids) == 2:
        return ", ".join(plan_ids)
    return f"{len(plan_ids)} plans"


def _summarize_group_ids(group_ids: list[str]) -> str:
    if not group_ids:
        return ""
    if len(group_ids) <= 3:
        return ", ".join(group_ids)
    return f"{', '.join(group_ids[:2])}, +{len(group_ids) - 2}"


def _render_implementing_progress(width: int, progress: dict[str, object]) -> list[str]:
    total = int(progress.get("total", 0))
    completed = int(progress.get("completed", 0))
    active_group = _extract_str(progress.get("active_group"))
    active_mode = _normalize_group_mode(progress.get("active_mode"))
    active_plan_ids = _extract_str_list(progress.get("active_plan_ids"))
    completed_group_ids = _extract_str_list(progress.get("completed_group_ids"))
    queued_group_ids = _extract_str_list(progress.get("queued_group_ids"))

    rows: list[str] = []
    rows.append(
        _compose_line(
            width,
            prefix_plain=" │   ",
            prefix_rendered=f" {CYAN}│{RESET}   ",
            left_plain=f"› groups: {completed}/{total} done",
            left_rendered=f"{DIM}› groups: {completed}/{total} done{RESET}",
        )
    )

    active_parts = [part for part in (active_group, active_mode) if part]
    active_text = " ".join(active_parts)
    plan_summary = _format_plan_summary(active_plan_ids)
    if plan_summary:
        active_text = f"{active_text} · {plan_summary}" if active_text else plan_summary
    if active_text:
        rows.append(
            _compose_line(
                width,
                prefix_plain=" │   ",
                prefix_rendered=f" {CYAN}│{RESET}   ",
                left_plain=f"› active: {active_text}",
                left_rendered=f"{DIM}› active: {active_text}{RESET}",
            )
        )

    summary_parts: list[str] = []
    done_summary = _summarize_group_ids(completed_group_ids)
    queued_summary = _summarize_group_ids(queued_group_ids)
    if done_summary:
        summary_parts.append(f"done: {done_summary}")
    if queued_summary:
        summary_parts.append(f"queued: {queued_summary}")
    if summary_parts:
        summary_text = " · ".join(summary_parts)
        rows.append(
            _compose_line(
                width,
                prefix_plain=" │   ",
                prefix_rendered=f" {CYAN}│{RESET}   ",
                left_plain=f"› {summary_text}",
                left_rendered=f"{DIM}› {summary_text}{RESET}",
            )
        )
    return rows


def _render_pipeline_section(
    width: int,
    *,
    state: dict[str, object],
    status: str,
    last_event: str,
    interruption_cause: str,
    review_iter: int,
    subplan_count: int,
) -> list[str]:
    lines = [_section_title("PIPELINE"), ""]
    display_stages = [stage for stage in PIPELINE_STATES if stage not in OPTIONAL_PHASES or stage == status]
    gutter_plain = " │ "

    try:
        current_idx = PIPELINE_STATES.index(status)
    except ValueError:
        current_idx = -1

    active_added = False
    for stage in display_stages:
        stage_label = stage.replace("_", " ")
        try:
            stage_idx = PIPELINE_STATES.index(stage)
        except ValueError:
            stage_idx = current_idx + 1

        if stage == status:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=gutter_plain,
                    prefix_rendered=f" {CYAN}│{RESET} ",
                    left_plain=f"▶ {stage_label}",
                    left_rendered=f"{BOLD}{CYAN}▶ {stage_label}{RESET}",
                )
            )
            if last_event:
                lines.append(
                    _compose_line(
                        width,
                        prefix_plain=" │   ",
                        prefix_rendered=f" {CYAN}│{RESET}   ",
                        left_plain=f"› {format_event(last_event)}",
                        left_rendered=f"{DIM}› {format_event(last_event)}{RESET}",
                    )
                )
            if review_iter:
                lines.append(
                    _compose_line(
                        width,
                        prefix_plain=" │   ",
                        prefix_rendered=f" {CYAN}│{RESET}   ",
                        left_plain=f"› iter {review_iter}",
                        left_rendered=f"{DIM}› iter {review_iter}{RESET}",
                    )
                )
            progress = _extract_execution_progress(state) if stage == "implementing" else None
            if progress is not None:
                lines.extend(_render_implementing_progress(width, progress))
            elif subplan_count > 1:
                lines.append(
                    _compose_line(
                        width,
                        prefix_plain=" │   ",
                        prefix_rendered=f" {CYAN}│{RESET}   ",
                        left_plain=f"› {subplan_count} subplans",
                        left_rendered=f"{DIM}› {subplan_count} subplans{RESET}",
                    )
                )
            active_added = True
        elif stage_idx < current_idx:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=gutter_plain,
                    prefix_rendered=f" {GREEN}│{RESET} ",
                    left_plain=f"✓ {stage_label}",
                    left_rendered=f"{GREEN}✓{RESET} {DIM}{stage_label}{RESET}",
                )
            )
        else:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=gutter_plain,
                    prefix_rendered=f" {DIM}│{RESET} ",
                    left_plain=f"· {stage_label}",
                    left_rendered=f"{DIM}· {stage_label}{RESET}",
                )
            )

    if status not in PIPELINE_STATES and status != "waiting…" and not active_added:
        status_label = status.replace("_", " ")
        lines.append(
            _compose_line(
                width,
                prefix_plain=gutter_plain,
                prefix_rendered=f" {CYAN}│{RESET} ",
                left_plain=f"▶ {status_label}",
                left_rendered=f"{BOLD}{CYAN}▶ {status_label}{RESET}",
            )
        )
        if last_event:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=" │   ",
                    prefix_rendered=f" {CYAN}│{RESET}   ",
                    left_plain=f"› {format_event(last_event)}",
                    left_rendered=f"{DIM}› {format_event(last_event)}{RESET}",
                )
            )
        if interruption_cause:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=" │   ",
                    prefix_rendered=f" {CYAN}│{RESET}   ",
                    left_plain=f"› cause: {interruption_cause}",
                    left_rendered=f"{DIM}› cause: {interruption_cause}{RESET}",
                )
            )

    return lines


def _render_agents_section(
    width: int,
    *,
    agents: dict[str, dict[str, str]],
    role_states: dict[str, str],
    role_labels: dict[str, str],
) -> list[str]:
    lines = [_section_title("AGENTS"), ""]

    def _agent_row(display_name: str, agent_state: str, cfg: dict[str, str]) -> None:
        if agent_state == "working":
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=" ",
                    prefix_rendered=" ",
                    left_plain=f"● {display_name}",
                    left_rendered=f"{CYAN}●{RESET} {BOLD}{display_name}{RESET}",
                    right_plain="[ WORKING ]",
                    right_rendered=f"{GREEN}[ WORKING ]{RESET}",
                )
            )
        elif agent_state == "idle":
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=" ",
                    prefix_rendered=" ",
                    left_plain=f"○ {display_name}",
                    left_rendered=f"{DIM}○{RESET} {display_name}",
                    right_plain="[ IDLE ]",
                    right_rendered=f"{YELLOW}[ IDLE ]{RESET}",
                )
            )
        else:
            return
        cli = cfg.get("cli", "?")
        model = trim_model(cfg.get("model", ""), cli)
        info = _truncate_text(f"{cli}/{model}", max(1, width - 3))
        lines.append(f"   {DIM}{info}{RESET}")
        lines.append("")

    for role, cfg in agents.items():
        if role == "coder":
            parallel_keys = sorted(
                [key for key in role_states if key.startswith("coder_")],
                key=lambda key: int(key.split("_")[1]) if key.split("_")[1].isdigit() else 0,
            )
            if parallel_keys:
                for coder_key in parallel_keys:
                    if role_states.get(coder_key, "inactive") == "inactive":
                        continue
                    _agent_row(
                        role_labels.get(coder_key, f"coder {coder_key.split('_')[1]}"),
                        role_states.get(coder_key, "inactive"),
                        cfg,
                    )
            elif role_states.get("coder", "inactive") != "inactive":
                _agent_row(role_labels.get("coder", "coder"), role_states.get("coder", "inactive"), cfg)
        elif role_states.get(role, "inactive") != "inactive":
            _agent_row(role_labels.get(role, role), role_states.get(role, "inactive"), cfg)

    if lines[-1] == "":
        lines.pop()
    return lines


def _render_research_section(width: int, state: dict, feature_dir: Path) -> list[str]:
    code_tasks = state.get("research_tasks", {})
    web_tasks = state.get("web_research_tasks", {})
    if not code_tasks and not web_tasks:
        return []

    research_dir = feature_dir / SESSION_DIR_NAMES["research"]
    all_tasks = [("c", topic, f"code-{topic}/done") for topic in code_tasks] + [
        ("w", topic, f"web-{topic}/done") for topic in web_tasks
    ]
    done_count = sum(1 for _, _, marker in all_tasks if (research_dir / marker).exists())
    rows = [_section_title(f"RESEARCH {done_count}/{len(all_tasks)}"), ""]
    pulse_on = int(time.time()) % 2 == 0
    for type_prefix, topic, marker in all_tasks:
        done = (research_dir / marker).exists()
        slug = _truncate_text(topic, max(1, width - 7))
        if done:
            rows.append(f" {GREEN}✓{RESET} {DIM}{type_prefix}·{RESET} {slug}")
        elif pulse_on:
            rows.append(f" {YELLOW}{_spinner_frame()}{RESET} {DIM}{type_prefix}·{RESET} {BOLD}{slug}{RESET}")
        else:
            rows.append(f" {DIM}{_spinner_frame()}{RESET} {DIM}{type_prefix}· {slug}{RESET}")
    return rows


def render(
    session_name: str,
    state_path: Path,
    runtime_state_path: Path,
    agents: dict[str, dict[str, str]],
    width: int,
    height: int,
    start_time: float,
    log_path: Path | None = None,
) -> str:
    state = load_state(state_path)
    role_states = get_role_states(session_name, runtime_state_path)
    role_labels = get_role_labels(state_path, runtime_state_path)
    created_files_log_path = state_path.parent / "created_files.log"

    status = state.get("phase", "waiting…")
    last_event = str(state.get("last_event", "")).strip()
    interruption_cause = str(state.get("interruption_cause", "")).strip()
    review_iter = state.get("review_iteration", 0)
    subplan_count = state.get("subplan_count", 0)

    body: list[str] = []
    header_rows = _render_feature_header(width, state_path)
    if header_rows:
        body.extend(header_rows)
    body.append(_separator(width))
    body.append("")
    body.extend(
        _render_pipeline_section(
            width,
            state=state,
            status=status,
            last_event=last_event,
            interruption_cause=interruption_cause,
            review_iter=review_iter,
            subplan_count=subplan_count,
        )
    )

    agent_rows = _render_agents_section(width, agents=agents, role_states=role_states, role_labels=role_labels)
    if agent_rows:
        body.append("")
        body.extend(agent_rows)

    research_rows = _render_research_section(width, state, state_path.parent)
    if research_rows:
        body.append("")
        body.extend(research_rows)

    elapsed_seconds = max(0, int(time.time() - start_time))
    hours = elapsed_seconds // 3600
    minutes = (elapsed_seconds % 3600) // 60
    seconds = elapsed_seconds % 60
    footer = [_separator(width), f"{DIM}◷ {hours}:{minutes:02d}:{seconds:02d}{RESET}"]

    log_rows: list[str] = []
    if log_path is not None:
        reserved = len(body) + len(footer)
        available_for_log = height - reserved - 1
        if available_for_log >= 2:
            entries = read_monitor_log_entries(log_path, created_files_log_path, max(1, available_for_log - 2))
            if entries:
                log_rows = [_section_title("LOG"), ""]
                max_message = max(1, width - 8)
                for entry in entries:
                    message = _truncate_text(entry.message, max_message)
                    rendered = f"{WHITE}{message}{RESET}" if entry.phase_event else message
                    log_rows.append(f" {DIM}{entry.time_str}{RESET} {rendered}")

    lines = list(body)
    if log_rows:
        lines.append("")
        lines.extend(log_rows)

    target_body = max(0, height - len(footer))
    while len(lines) < target_body:
        lines.append("")
    return "\n".join((lines[:target_body] + footer)[:height])
