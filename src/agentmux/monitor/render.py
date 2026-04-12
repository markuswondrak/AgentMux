from __future__ import annotations

import os
import re
import textwrap
import time
from pathlib import Path

from agentmux.terminal_ui.colors import PRIMARY, SECONDARY
from agentmux.terminal_ui.hyperlinks import OSC8_RE, file_hyperlink

from ..shared.models import RuntimeFiles
from .progress_parser import ExecutionProgress, parse_execution_progress
from .state_reader import (
    OPTIONAL_PHASES,
    PIPELINE_STATES,
    format_event,
    get_role_labels,
    get_role_states,
    load_state,
    read_monitor_log_entries,
    read_session_summary,
    trim_model,
)

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[33m"
RED = "\033[31m"
WHITE = "\033[97m"

MONITOR_HEADER_LOGO = [
    (PRIMARY, "╭───────────╮"),
    (PRIMARY, "│ ▄▀█ █▀▄▀█ │"),
    (SECONDARY, "│ █▀█ █ ▀ █ │"),
    (SECONDARY, "╰───────────╯"),
]

_ANSI_RE = re.compile(rf"\033\[[0-9;]*m|{OSC8_RE}")


def get_terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 40, 24


def _vlen(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


def _vlines(text: str, width: int) -> int:
    """Return the number of visual terminal lines a string occupies."""
    if width <= 0:
        return 1
    visible = _vlen(text)
    if visible == 0:
        return 1
    return max(1, (visible + width - 1) // width)  # ceiling division


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


def _render_system_notice(width: int, notice: str) -> list[str]:
    """Render a prominent system notice/warning box."""
    if not notice:
        return []

    # Wrap notice text to fit width
    max_width = max(10, width - 4)
    wrapped = textwrap.wrap(notice, width=max_width)

    lines = []
    lines.append(f"{YELLOW}╭{'─' * (width - 2)}╮{RESET}")
    for line in wrapped:
        padded = line.ljust(width - 4)[: width - 4]
        lines.append(f"{YELLOW}│{RESET} {BOLD}{RED}{padded}{RESET} {YELLOW}│{RESET}")
    lines.append(f"{YELLOW}╰{'─' * (width - 2)}╯{RESET}")
    lines.append("")
    return lines


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
    wrapped = textwrap.wrap(
        clean, width=width, break_long_words=True, break_on_hyphens=False
    )
    if len(wrapped) > max_lines:
        head = wrapped[: max_lines - 1]
        tail = " ".join(wrapped[max_lines - 1 :])
        wrapped = head + [textwrap.shorten(tail, width=width, placeholder="…")]
    while len(wrapped) < max_lines:
        wrapped.append("")
    return wrapped[:max_lines]


def _render_feature_header(width: int, state_path: Path) -> list[str]:
    feature_request = read_session_summary(state_path)
    logo_width = max(_vlen(row) for _, row in MONITOR_HEADER_LOGO)
    gap = 2
    text_width = width - logo_width - gap

    if text_width >= 10:
        feature_lines = _wrap_feature_lines(
            feature_request, text_width, max_lines=len(MONITOR_HEADER_LOGO)
        )
        rows: list[str] = []
        for (color, logo_row), feature_line in zip(
            MONITOR_HEADER_LOGO, feature_lines, strict=False
        ):
            padded_logo = logo_row + (" " * max(0, logo_width - _vlen(logo_row)))
            logo_text = f"{BOLD}{color}{padded_logo}{RESET}"
            rows.append(
                f"{logo_text}{' ' * gap}{feature_line}" if feature_line else logo_text
            )
        return rows

    if width >= logo_width:
        rows = [
            f"{BOLD}{color}{logo_row}{RESET}" for color, logo_row in MONITOR_HEADER_LOGO
        ]
        if feature_request:
            rows.extend(
                line
                for line in _wrap_feature_lines(feature_request, width, max_lines=2)
                if line
            )
        return rows

    if feature_request:
        return [
            line
            for line in _wrap_feature_lines(feature_request, max(1, width), max_lines=2)
            if line
        ]
    return []


def _format_plan_summary(plan_ids: list[str]) -> str:
    if not plan_ids:
        return ""
    if len(plan_ids) == 1:
        return plan_ids[0]
    if len(plan_ids) == 2:
        return ", ".join(plan_ids)
    return f"{len(plan_ids)} plans"


def _render_implementing_progress(width: int, progress: ExecutionProgress) -> list[str]:
    total = progress.total
    completed = progress.completed
    active_group = progress.active_group
    active_mode = progress.active_mode
    active_plan_ids = progress.active_plan_ids
    completed_group_ids = progress.completed_group_ids
    queued_group_ids = progress.queued_group_ids

    rows: list[str] = []

    # Summary header
    rows.append(
        _compose_line(
            width,
            prefix_plain=" │   ",
            prefix_rendered=f" {SECONDARY}│{RESET}   ",
            left_plain=f"› groups: {completed}/{total} done",
            left_rendered=f"{DIM}› groups: {completed}/{total} done{RESET}",
        )
    )

    # Completed groups
    for group_id in completed_group_ids:
        rows.append(
            _compose_line(
                width,
                prefix_plain=" │   ",
                prefix_rendered=f" {SECONDARY}│{RESET}   ",
                left_plain=f"› ✓ {group_id}",
                left_rendered=f"{DIM}› {GREEN}✓{RESET} {DIM}{group_id}{RESET}",
            )
        )

    # Active group
    if active_group:
        active_parts = [part for part in (active_group, active_mode) if part]
        active_text = " ".join(active_parts)
        plan_summary = _format_plan_summary(active_plan_ids)
        if plan_summary:
            active_text = (
                f"{active_text} · {plan_summary}" if active_text else plan_summary
            )
        if active_text:
            rows.append(
                _compose_line(
                    width,
                    prefix_plain=" │   ",
                    prefix_rendered=f" {SECONDARY}│{RESET}   ",
                    left_plain=f"› ▶ {active_text}",
                    left_rendered=(
                        f"{DIM}› {BOLD}{SECONDARY}▶{RESET} "
                        f"{BOLD}{SECONDARY}{active_text}{RESET}"
                    ),
                )
            )

    # Queued groups
    for group_id in queued_group_ids:
        rows.append(
            _compose_line(
                width,
                prefix_plain=" │   ",
                prefix_rendered=f" {SECONDARY}│{RESET}   ",
                left_plain=f"› · {group_id}",
                left_rendered=f"{DIM}› · {group_id}{RESET}",
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
    display_stages = [
        stage
        for stage in PIPELINE_STATES
        if stage not in OPTIONAL_PHASES or stage == status
    ]
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
                    prefix_rendered=f" {SECONDARY}│{RESET} ",
                    left_plain=f"▶ {stage_label}",
                    left_rendered=f"{BOLD}{SECONDARY}▶ {stage_label}{RESET}",
                )
            )
            if last_event:
                lines.append(
                    _compose_line(
                        width,
                        prefix_plain=" │   ",
                        prefix_rendered=f" {SECONDARY}│{RESET}   ",
                        left_plain=f"› {format_event(last_event)}",
                        left_rendered=f"{DIM}› {format_event(last_event)}{RESET}",
                    )
                )
            if review_iter:
                lines.append(
                    _compose_line(
                        width,
                        prefix_plain=" │   ",
                        prefix_rendered=f" {SECONDARY}│{RESET}   ",
                        left_plain=f"› iter {review_iter}",
                        left_rendered=f"{DIM}› iter {review_iter}{RESET}",
                    )
                )
            progress = (
                parse_execution_progress(state) if stage == "implementing" else None
            )
            if progress is not None:
                lines.extend(_render_implementing_progress(width, progress))
            elif subplan_count > 1:
                lines.append(
                    _compose_line(
                        width,
                        prefix_plain=" │   ",
                        prefix_rendered=f" {SECONDARY}│{RESET}   ",
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
                prefix_rendered=f" {SECONDARY}│{RESET} ",
                left_plain=f"▶ {status_label}",
                left_rendered=f"{BOLD}{SECONDARY}▶ {status_label}{RESET}",
            )
        )
        if last_event:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=" │   ",
                    prefix_rendered=f" {SECONDARY}│{RESET}   ",
                    left_plain=f"› {format_event(last_event)}",
                    left_rendered=f"{DIM}› {format_event(last_event)}{RESET}",
                )
            )
        if interruption_cause:
            lines.append(
                _compose_line(
                    width,
                    prefix_plain=" │   ",
                    prefix_rendered=f" {SECONDARY}│{RESET}   ",
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
                    left_rendered=f"{SECONDARY}●{RESET} {BOLD}{display_name}{RESET}",
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
                key=lambda key: (
                    int(key.split("_")[1]) if key.split("_")[1].isdigit() else 0
                ),
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
                _agent_row(
                    role_labels.get("coder", "coder"),
                    role_states.get("coder", "inactive"),
                    cfg,
                )
        elif role_states.get(role, "inactive") != "inactive":
            _agent_row(
                role_labels.get(role, role), role_states.get(role, "inactive"), cfg
            )

    if lines[-1] == "":
        lines.pop()
    return lines


def _render_research_section(width: int, state: dict) -> list[str]:
    code_tasks = state.get("research_tasks", {})
    web_tasks = state.get("web_research_tasks", {})
    if not code_tasks and not web_tasks:
        return []

    all_tasks = [("c", topic, str(status)) for topic, status in code_tasks.items()] + [
        ("w", topic, str(status)) for topic, status in web_tasks.items()
    ]
    done_count = sum(1 for _, _, status in all_tasks if status == "done")
    rows = [_section_title(f"RESEARCH {done_count}/{len(all_tasks)}"), ""]
    pulse_on = int(time.time()) % 2 == 0
    for type_prefix, topic, status in all_tasks:
        done = status == "done"
        slug = _truncate_text(topic, max(1, width - 7))
        if done:
            rows.append(f" {GREEN}✓{RESET} {DIM}{type_prefix}·{RESET} {slug}")
        elif pulse_on:
            rows.append(
                f" {YELLOW}{_spinner_frame()}{RESET} {DIM}{type_prefix}·{RESET} "
                f"{BOLD}{slug}{RESET}"
            )
        else:
            rows.append(
                f" {DIM}{_spinner_frame()}{RESET} {DIM}{type_prefix}· {slug}{RESET}"
            )
    return rows


class Monitor:
    """Monitor renderer with static configuration captured at instantiation."""

    def __init__(
        self,
        session_name: str,
        files: RuntimeFiles,
        agents: dict[str, dict[str, str]],
    ):
        self.session_name = session_name
        self.files = files
        self.agents = agents
        self._start_time = time.time()

    def render(self, width: int, height: int) -> str:
        """Render a single frame given current terminal dimensions."""
        state = load_state(self.files.state)
        role_states = get_role_states(self.session_name, self.files.runtime_state)
        role_labels = get_role_labels(self.files.state, self.files.runtime_state)
        created_files_log_path = self.files.created_files_log

        status = state.get("phase", "waiting…")
        last_event = str(state.get("last_event", "")).strip()
        interruption_cause = str(state.get("interruption_cause", "")).strip()
        review_iter = state.get("review_iteration", 0)
        subplan_count = state.get("subplan_count", 0)
        system_notice = str(state.get("system_notice", "")).strip()

        body: list[str] = []

        # Render system notice if present (external fix warning)
        if system_notice:
            body.extend(_render_system_notice(width, system_notice))

        header_rows = _render_feature_header(width, self.files.state)
        if header_rows:
            body.extend(header_rows)
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

        agent_rows = _render_agents_section(
            width, agents=self.agents, role_states=role_states, role_labels=role_labels
        )
        if agent_rows:
            body.append("")
            body.extend(agent_rows)

        research_rows = _render_research_section(width, state)
        if research_rows:
            body.append("")
            body.extend(research_rows)

        elapsed_seconds = max(0, int(time.time() - self._start_time))
        hours = elapsed_seconds // 3600
        minutes = (elapsed_seconds % 3600) // 60
        seconds = elapsed_seconds % 60
        footer = [
            _separator(width),
            f"{DIM}◷ {hours}:{minutes:02d}:{seconds:02d}  │  "
            f"{self.session_name}{RESET}",
        ]
        footer_visual_lines = sum(_vlines(line, width) for line in footer)

        log_rows: list[str] = []
        log_path = self.files.status_log
        if log_path is not None:
            reserved = len(body) + footer_visual_lines
            available_for_log = height - reserved - 1
            if available_for_log >= 2:
                entries = read_monitor_log_entries(
                    log_path, created_files_log_path, max(1, available_for_log - 2)
                )
                if entries:
                    log_rows = [_section_title("LOG"), ""]
                    max_message = max(1, width - 8)
                    feature_dir = self.files.feature_dir
                    for entry in entries:
                        message = _truncate_text(entry.message, max_message)
                        # Wrap file paths in OSC 8 hyperlinks for IDE Ctrl-click support
                        if entry.relative_path and message.startswith("+ "):
                            visible_path = message[2:]  # Strip "+ " prefix
                            abs_path = feature_dir / entry.relative_path
                            message = f"+ {file_hyperlink(abs_path, visible_path)}"
                        rendered = (
                            f"{WHITE}{message}{RESET}" if entry.phase_event else message
                        )
                        log_rows.append(f" {DIM}{entry.time_str}{RESET} {rendered}")

        lines = list(body)
        if log_rows:
            lines.append("")
            lines.extend(log_rows)

        target_body = max(0, height - footer_visual_lines)
        while len(lines) < target_body:
            lines.append("")
        return "\n".join((lines[:target_body] + footer)[:height])
