#!/usr/bin/env python3
"""Control pane monitor for the multi-agent pipeline."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
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


def _box_top(width: int, label: str = "PIPELINE") -> str:
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


def _format_event(raw: str) -> str:
    return EVENT_LABELS.get(raw, raw.replace("_", " "))


def _render_research_section(width: int, state: dict, feature_dir: Path) -> list[str]:
    """Return box rows for the RESEARCH section, or [] if no tasks exist."""
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

    rows: list[str] = []
    rows.append(_box_divider(width, f"RESEARCH {done_count}/{total}"))
    rows.append(_box_row(width))

    pulse_on = int(time.time()) % 2 == 0
    max_topic = max(1, width - 2 - 6)  # inner minus " X p· "

    for type_prefix, topic, marker in all_tasks:
        done = (research_dir / marker).exists()
        slug = topic if len(topic) <= max_topic else topic[: max_topic - 1] + "…"
        if done:
            icon = f"{GREEN}✓{RESET}"
            label = f"{DIM}{type_prefix}·{RESET}{slug}"
            rows.append(_box_row(width, f" {icon} {label}"))
        else:
            if pulse_on:
                icon = f"{YELLOW}⟳{RESET}"
                label = f"{DIM}{type_prefix}·{RESET}{BOLD}{slug}{RESET}"
            else:
                icon = f"{DIM}⟳{RESET}"
                label = f"{DIM}{type_prefix}·{slug}{RESET}"
            rows.append(_box_row(width, f" {icon} {label}"))

    rows.append(_box_row(width))
    return rows


def _render_documents_section(width: int, feature_dir: Path) -> list[str]:
    present = [filename for filename in DOCUMENT_FILES if (feature_dir / filename).exists()]
    if not present:
        return []

    rows = [_box_divider(width, "DOCUMENTS"), _box_row(width)]
    for filename in present:
        rows.append(_box_row(width, f" {GREEN}✓{RESET} {DIM}{filename}{RESET}"))
    rows.append(_box_row(width))
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

    inner = width - 2
    lines: list[str] = []

    # ── top border ────────────────────────────────────────────────────────
    lines.append(_box_top(width))

    # ── feature request ───────────────────────────────────────────────────
    feature_request = _read_feature_request(state_path)
    if feature_request:
        max_len = max(1, inner - 2)
        if len(feature_request) > max_len:
            feature_request = feature_request[: max_len - 1] + "…"
        lines.append(_box_row(width, f" {DIM}{feature_request}{RESET}"))
        lines.append(_box_divider(width))

    # ── pipeline stages ───────────────────────────────────────────────────
    max_stage = max(1, inner - 5)
    display_stages = [
        stage
        for stage in PIPELINE_STATES
        if stage not in OPTIONAL_PHASES or stage == status
    ]
    lines.append(_box_row(width))
    for stage in display_stages:
        display = stage[:max_stage]
        if stage == status:
            color = CYAN if stage in OPTIONAL_PHASES else status_color(stage)
            lines.append(_box_row(width, f"  {BOLD}{color}▶ {display}{RESET}"))
        else:
            lines.append(_box_row(width, f"  {DIM}· {display}{RESET}"))
    lines.append(_box_row(width))

    # unknown status not in list
    if status not in PIPELINE_STATES and status != "waiting…":
        color = status_color(status)
        display = status[:max_stage]
        lines.append(_box_row(width, f"  {BOLD}{color}▶ {display}{RESET}"))

    # extra pipeline metadata
    if last_event:
        label = _format_event(last_event)
        max_ev = max(1, inner - 5)
        ev = label if len(label) <= max_ev else label[: max_ev - 1] + "…"
        lines.append(_box_row(width, f"   {DIM}↳{RESET} {DIM}{ev}{RESET}"))
    if review_iter:
        lines.append(_box_row(width, f"   {DIM}iter {review_iter}{RESET}"))
    if subplan_count > 1:
        lines.append(_box_row(width, f"   {DIM}{subplan_count} subplans{RESET}"))

    # ── agents ────────────────────────────────────────────────────────────
    lines.append(_box_divider(width, "AGENTS"))
    lines.append(_box_row(width))

    def _agent_row(display_name: str, agent_state: str, cfg: dict[str, str]) -> None:
        max_name = 8
        if agent_state == "working":
            bullet = f"{GREEN}●{RESET}"
            label = f"{GREEN}WORKING{RESET}"
            name = f"{BOLD}{display_name:<{max_name}}{RESET}"
        elif agent_state == "idle":
            bullet = f"{YELLOW}●{RESET}"
            label = f"{YELLOW}IDLE{RESET}"
            name = f"{display_name:<{max_name}}"
        else:
            bullet = f"{DIM}○{RESET}"
            label = f"{DIM}inactive{RESET}"
            name = f"{DIM}{display_name:<{max_name}}{RESET}"
        lines.append(_box_row(width, f" {bullet} {name} {label}"))
        cli = cfg.get("cli", "?")
        model = _trim_model(cfg.get("model", ""), cli)
        info = f"{cli}/{model}"
        max_info = max(1, inner - 4)
        if len(info) > max_info:
            info = info[: max_info - 1] + "…"
        lines.append(_box_row(width, f"   {DIM}{info}{RESET}"))
        lines.append(_box_row(width))

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
                    num = ckey.split("_")[1]
                    _agent_row(f"coder {num}", role_states.get(ckey, "inactive"), cfg)
            else:
                if role_states.get("coder", "inactive") == "inactive":
                    continue
                _agent_row("coder", role_states.get("coder", "inactive"), cfg)
        else:
            if role_states.get(role, "inactive") == "inactive":
                continue
            _agent_row(role, role_states.get(role, "inactive"), cfg)

    # ── research tasks ────────────────────────────────────────────────────
    lines.extend(_render_research_section(width, state, state_path.parent))
    lines.extend(_render_documents_section(width, state_path.parent))

    # ── event log (fills remaining height, pinned above footer) ──────────
    if log_path is not None:
        footer_height = 3  # divider + elapsed + bottom
        available_for_log = height - len(lines) - footer_height
        # min 2 rows to bother showing (divider + at least one entry)
        if available_for_log >= 2:
            max_entries = available_for_log - 1  # -1 for the LOG divider
            entries = _read_event_log(log_path, max_entries)
            if entries:
                lines.append(_box_divider(width, "LOG"))
                max_phase = max(1, inner - 9)  # " HH:MM phase" = 1+5+1+phase
                for ts, phase in entries:
                    ph = phase[:max_phase]
                    lines.append(_box_row(width, f" {DIM}{ts}  {ph}{RESET}"))

    # ── elapsed footer (pinned to bottom) ─────────────────────────────────
    elapsed_seconds = max(0, int(time.time() - start_time))
    hours = elapsed_seconds // 3600
    minutes = (elapsed_seconds % 3600) // 60
    seconds = elapsed_seconds % 60
    elapsed_str = f"{hours}:{minutes:02d}:{seconds:02d}"

    footer = [
        _box_divider(width),
        _box_row(width, f" {DIM}↑ {elapsed_str}{RESET}"),
        _box_bottom(width),
    ]

    # pad middle with empty box rows so footer sits at the bottom
    target_body = height - len(footer)
    while len(lines) < target_body:
        lines.append(_box_row(width))

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
