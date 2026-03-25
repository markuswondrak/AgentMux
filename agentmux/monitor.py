#!/usr/bin/env python3
"""Control pane monitor for the multi-agent pipeline."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from .config import infer_project_dir, load_layered_config

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"   # bright green – phosphor
YELLOW = "\033[33m"  # amber – idle / warning
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"

# Box-drawing characters (double-line style)
_TL = "╔"
_TR = "╗"
_BL = "╚"
_BR = "╝"
_ML = "╠"
_MR = "╣"
_V = "║"
_H = "═"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

ALWAYS_VISIBLE_STATES = [
    "product_management",
    "planning",
    "implementing",
    "reviewing",
    "completing",
    "done",
]
OPTIONAL_PHASES = {"designing", "fixing", "documenting"}
PIPELINE_STATES = [
    "product_management",
    "planning",
    "designing",
    "implementing",
    "reviewing",
    "fixing",
    "completing",
    "documenting",
    "done",
]
EVENT_LABELS: dict[str, str] = {
    "feature_created": "starting up",
    "resumed": "resumed",
    "plan_written": "plan ready",
    "design_written": "design ready",
    "research_dispatched": "researching…",
    "research_complete": "research done",
    "web_research_dispatched": "web research…",
    "web_research_complete": "web research done",
    "implementation_started": "coding…",
    "implementation_completed": "code done",
    "review_written": "review ready",
    "fix_requested": "fix needed",
    "fix_completed": "fix done",
    "docs_written": "docs ready",
    "approved": "approved ✓",
    "changes_requested": "changes asked",
    "plan_approved": "plan approved",
    "confirmation_sent": "awaiting ok",
    "pm_completed": "pm done",
}
DOCUMENT_FILES = [
    "planning/plan.md",
    "planning/tasks.md",
    "design/design.md",
    "review/review.md",
    "completion/changes.md",
]


def get_terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 40, 24


def _vlen(s: str) -> int:
    """Visible (printable) length, stripping ANSI escape codes."""
    return len(_ANSI_RE.sub("", s))


def _box_top(width: int, label: str = "AgentMux") -> str:
    inner = width - 2
    padded = f" {label} "
    right_fill = max(0, inner - 2 - len(padded))
    return f"{DIM}{_TL}{_H * 2}{RESET}{BOLD}{padded}{RESET}{DIM}{_H * right_fill}{_TR}{RESET}"


def _box_divider(width: int, label: str = "") -> str:
    inner = width - 2
    if label:
        padded = f" {label} "
        right_fill = max(0, inner - 2 - len(padded))
        return f"{DIM}{_ML}{_H * 2}{RESET}{DIM}{padded}{RESET}{DIM}{_H * right_fill}{_MR}{RESET}"
    return f"{DIM}{_ML}{_H * inner}{_MR}{RESET}"


def _box_bottom(width: int) -> str:
    inner = width - 2
    return f"{DIM}{_BL}{_H * inner}{_BR}{RESET}"


def _box_row(width: int, text: str = "") -> str:
    """Wrap *text* in box side-borders, padding to fill the inner width."""
    inner = width - 2
    vl = _vlen(text)
    if vl > inner:
        # strip ANSI, truncate, no re-color
        clean = _ANSI_RE.sub("", text)
        text = clean[: inner - 1] + "…"
        vl = inner
    pad = inner - vl
    return f"{DIM}{_V}{RESET}{text}{' ' * pad}{DIM}{_V}{RESET}"


# ---------------------------------------------------------------------------

def load_runtime_registry(runtime_state_path: Path) -> dict[str, str | None]:
    try:
        raw = json.loads(runtime_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    registry = {
        str(role): pane_id if pane_id is None else str(pane_id)
        for role, pane_id in dict(raw.get("primary", {})).items()
    }
    for role, workers in dict(raw.get("parallel", {})).items():
        for worker_key, pane_id in dict(workers).items():
            registry[f"{role}_{worker_key}"] = None if pane_id is None else str(pane_id)
    return registry


def get_role_states(session_name: str, runtime_state_path: Path) -> dict[str, str]:
    """Return mapping of role key → 'working' | 'idle' | 'inactive'."""
    registry = load_runtime_registry(runtime_state_path)
    if not registry:
        legacy_path = runtime_state_path.parent / "panes.json"
        try:
            registry = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    try:
        result_all = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-a", "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        all_ids = {t.strip() for t in result_all.stdout.splitlines() if t.strip()}

        result_pipeline = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session_name}:pipeline", "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        pipeline_ids = {t.strip() for t in result_pipeline.stdout.splitlines() if t.strip()}
    except Exception:
        return {}

    states: dict[str, str] = {}
    for role, pane_id in registry.items():
        if role.startswith("_") or pane_id is None:
            continue
        if pane_id in pipeline_ids:
            states[role] = "working"
        elif pane_id in all_ids:
            states[role] = "idle"
        else:
            states[role] = "inactive"
    return states


def load_state(state_path: Path) -> dict:
    try:
        text = state_path.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
    except Exception:
        pass
    return {}


def status_color(status: str) -> str:
    if status in ("done",):
        return GREEN
    if status in ("failed",):
        return RED
    if status in ("completing", "reviewing"):
        return YELLOW
    return GREEN


def _trim_model(model: str, cli: str) -> str:
    """Strip vendor prefix matching CLI name."""
    prefix = f"{cli}-"
    if model.lower().startswith(prefix.lower()):
        model = model[len(prefix):]
    return model


def _read_event_log(log_path: Path, n: int) -> list[tuple[str, str]]:
    """Return the last *n* entries from status_log.txt as (time_str, phase) pairs."""
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception:
        return []
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.strip().split()
        # Format: "2026-03-21 14:30:00  implementing"
        if len(parts) >= 3:
            time_str = parts[1][:5]  # HH:MM
            phase = parts[2]
            entries.append((time_str, phase))
        elif len(parts) == 2:
            time_str = parts[0][:5]
            phase = parts[1]
            entries.append((time_str, phase))
    return entries[-n:] if entries else []


def _read_feature_request(state_path: Path) -> str:
    requirements_path = state_path.parent / "requirements.md"
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    in_initial_request = False
    for line in lines:
        stripped = line.strip()
        if not in_initial_request:
            if stripped == "## Initial Request":
                in_initial_request = True
            continue
        if stripped:
            return stripped
    return ""


def _load_header_logo() -> list[tuple[str, str]]:
    logo_path = Path(__file__).resolve().parent.parent / "logo.md"
    try:
        raw = logo_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return [
            (CYAN, "╭───────────╮"),
            (CYAN, "│ AGENTMUX │"),
            (MAGENTA, "╰───────────╯"),
        ]

    lines: list[str] = []
    in_block = False
    for line in raw:
        if line.strip() == "```":
            if in_block:
                break
            in_block = True
            continue
        if in_block:
            lines.append(line)

    if not lines:
        lines = [line.rstrip("\n") for line in raw if line.strip()]
    if not lines:
        lines = [
            "╭───────────╮",
            "│ AGENTMUX │",
            "╰───────────╯",
        ]

    logo: list[tuple[str, str]] = []
    for idx, line in enumerate(lines):
        if idx in (0, 1):
            color = CYAN
        else:
            color = MAGENTA
        logo.append((color, line))
    return logo


def _wrap_feature_lines(text: str, width: int, *, max_lines: int = 4) -> list[str]:
    if width <= 0:
        return [""] * max_lines
    clean = " ".join(text.split())
    if not clean:
        return [""] * max_lines

    wrapped = textwrap.wrap(
        clean,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    )
    if len(wrapped) > max_lines:
        head = wrapped[: max_lines - 1]
        tail = " ".join(wrapped[max_lines - 1 :])
        shortened = textwrap.shorten(tail, width=width, placeholder="…")
        wrapped = head + [shortened]
    while len(wrapped) < max_lines:
        wrapped.append("")
    return wrapped[:max_lines]


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


def _render_feature_header(width: int, state_path: Path) -> list[str]:
    feature_request = _read_feature_request(state_path)
    header_logo = _load_header_logo()
    if not header_logo:
        return []
    logo_width = max(_vlen(row) for _, row in header_logo)
    gap = 2
    text_width = width - logo_width - gap

    if text_width >= 10:
        feature_lines = _wrap_feature_lines(feature_request, text_width, max_lines=len(header_logo))
        rows: list[str] = []
        for (color, logo_row), feature_line in zip(header_logo, feature_lines):
            padded_logo = logo_row + (" " * max(0, logo_width - _vlen(logo_row)))
            logo_text = f"{BOLD}{color}{padded_logo}{RESET}"
            rows.append(f"{logo_text}{' ' * gap}{feature_line}" if feature_line else logo_text)
        return rows

    if width >= logo_width:
        rows = [f"{BOLD}{color}{logo_row}{RESET}" for color, logo_row in header_logo]
        if feature_request:
            rows.extend(line for line in _wrap_feature_lines(feature_request, width, max_lines=2) if line)
        return rows

    if feature_request:
        return [line for line in _wrap_feature_lines(feature_request, max(1, width), max_lines=2) if line]
    return []


def _format_event(raw: str) -> str:
    return EVENT_LABELS.get(raw, raw.replace("_", " "))


def _render_pipeline_section(
    width: int,
    *,
    status: str,
    last_event: str,
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
                        left_plain=f"› {_format_event(last_event)}",
                        left_rendered=f"{DIM}› {_format_event(last_event)}{RESET}",
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
            if subplan_count > 1:
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

    return lines


def _render_agents_section(
    width: int,
    *,
    agents: dict[str, dict[str, str]],
    role_states: dict[str, str],
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
        model = _trim_model(cfg.get("model", ""), cli)
        info = _truncate_text(f"{cli}/{model}", max(1, width - 3))
        lines.append(f"   {DIM}{info}{RESET}")
        lines.append("")

    for role, cfg in agents.items():
        if role == "coder":
            parallel_keys = sorted(
                [k for k in role_states if k.startswith("coder_")],
                key=lambda k: int(k.split("_")[1]) if k.split("_")[1].isdigit() else 0,
            )
            if parallel_keys:
                for ckey in parallel_keys:
                    if role_states.get(ckey, "inactive") == "inactive":
                        continue
                    _agent_row(f"coder {ckey.split('_')[1]}", role_states.get(ckey, "inactive"), cfg)
            else:
                if role_states.get("coder", "inactive") != "inactive":
                    _agent_row("coder", role_states.get("coder", "inactive"), cfg)
        else:
            if role_states.get(role, "inactive") != "inactive":
                _agent_row(role, role_states.get(role, "inactive"), cfg)

    if lines[-1] == "":
        lines.pop()
    return lines


def _render_research_section(width: int, state: dict, feature_dir: Path) -> list[str]:
    code_tasks = state.get("research_tasks", {})
    web_tasks = state.get("web_research_tasks", {})
    if not code_tasks and not web_tasks:
        return []

    research_dir = feature_dir / "research"
    all_tasks: list[tuple[str, str, str]] = [
        ("c", topic, f"code-{topic}/done") for topic in code_tasks
    ] + [
        ("w", topic, f"web-{topic}/done") for topic in web_tasks
    ]

    done_count = sum(1 for _, _, marker in all_tasks if (research_dir / marker).exists())
    total = len(all_tasks)

    rows = [_section_title(f"RESEARCH {done_count}/{total}"), ""]
    pulse_on = int(time.time()) % 2 == 0

    for type_prefix, topic, marker in all_tasks:
        done = (research_dir / marker).exists()
        slug = _truncate_text(topic, max(1, width - 7))
        if done:
            rows.append(f" {GREEN}✓{RESET} {DIM}{type_prefix}·{RESET} {slug}")
        else:
            if pulse_on:
                rows.append(f" {YELLOW}{_spinner_frame()}{RESET} {DIM}{type_prefix}·{RESET} {BOLD}{slug}{RESET}")
            else:
                rows.append(f" {DIM}{_spinner_frame()}{RESET} {DIM}{type_prefix}· {slug}{RESET}")
    return rows


def _render_documents_section(width: int, feature_dir: Path) -> list[str]:
    present = [filename for filename in DOCUMENT_FILES if (feature_dir / filename).exists()]
    if not present:
        return []

    rows = [_section_title("DOCUMENTS"), ""]
    for filename in present:
        rows.append(f" {GREEN}✓{RESET} {DIM}{_truncate_text(filename, max(1, width - 3))}{RESET}")
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

    status = state.get("phase", "waiting…")
    last_event = str(state.get("last_event", "")).strip()
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
            status=status,
            last_event=last_event,
            review_iter=review_iter,
            subplan_count=subplan_count,
        )
    )

    agent_rows = _render_agents_section(width, agents=agents, role_states=role_states)
    if agent_rows:
        body.append("")
        body.extend(agent_rows)

    research_rows = _render_research_section(width, state, state_path.parent)
    if research_rows:
        body.append("")
        body.extend(research_rows)

    document_rows = _render_documents_section(width, state_path.parent)
    if document_rows:
        body.append("")
        body.extend(document_rows)

    elapsed_seconds = max(0, int(time.time() - start_time))
    hours = elapsed_seconds // 3600
    minutes = (elapsed_seconds % 3600) // 60
    seconds = elapsed_seconds % 60
    elapsed_str = f"{hours}:{minutes:02d}:{seconds:02d}"
    footer = [_separator(width), f"{DIM}◷ {elapsed_str}{RESET}"]

    log_rows: list[str] = []
    if log_path is not None:
        reserved = len(body) + len(footer)
        spacer = 1
        available_for_log = height - reserved - spacer
        if available_for_log >= 2:
            max_entries = max(1, available_for_log - 2)
            entries = _read_event_log(log_path, max_entries)
            if entries:
                log_rows = [_section_title("LOG"), ""]
                max_phase = max(1, width - 8)
                for ts, phase in entries:
                    log_rows.append(f" {DIM}{ts}{RESET} › {_truncate_text(_format_event(phase), max_phase)}")

    lines = list(body)
    if log_rows:
        lines.append("")
        lines.extend(log_rows)

    target_body = max(0, height - len(footer))
    while len(lines) < target_body:
        lines.append("")

    all_lines = lines[:target_body] + footer
    return "\n".join(all_lines[:height])


def append_status_change(log_path: Path, prev_status: str | None, status: str) -> str | None:
    if not status:
        return prev_status
    if status == prev_status:
        return prev_status

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{ts}  {status}\n")
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--session-name", required=True)
    parser.add_argument("--config")
    args = parser.parse_args()

    feature_dir = Path(args.feature_dir)
    state_path = feature_dir / "state.json"
    runtime_state_path = feature_dir / "runtime_state.json"
    config_path = Path(args.config).resolve() if args.config else None

    loaded = load_layered_config(
        infer_project_dir(feature_dir),
        explicit_config_path=config_path,
    )
    agents = {
        role: {"cli": agent.cli, "model": agent.model}
        for role, agent in loaded.agents.items()
    }

    start_time = time.time()
    status_log_path = feature_dir / "status_log.txt"
    prev_status: str | None = None

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            width, height = get_terminal_size()
            output = render(
                args.session_name, state_path, runtime_state_path, agents,
                width, height, start_time, log_path=status_log_path,
            )
            sys.stdout.write("\033[H\033[2J" + output)
            sys.stdout.flush()
            state = load_state(state_path)
            prev_status = append_status_change(status_log_path, prev_status, state.get("phase", ""))
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
