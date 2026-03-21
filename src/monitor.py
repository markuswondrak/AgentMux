#!/usr/bin/env python3
"""Control pane monitor for the multi-agent pipeline."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"

PIPELINE_STATES = [
    "architect_requested",
    "plan_ready",
    "coder_requested",
    "implementation_done",
    "review_requested",
    "review_ready",
    "completion_pending",
    "completion_approved",
]


def get_terminal_size() -> tuple[int, int]:
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 40, 24


def get_active_roles(session_name: str, panes_path: Path) -> set[str]:
    """Return the set of agent roles that have a live tmux pane."""
    try:
        panes = json.loads(panes_path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    try:
        result = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session_name}:pipeline", "-F", "#{pane_id}"],
            capture_output=True,
            text=True,
            check=False,
        )
        live_ids = {t.strip() for t in result.stdout.splitlines() if t.strip()}
    except Exception:
        return set()

    active: set[str] = set()
    for role, pane_id in panes.items():
        if role.startswith("_") or pane_id is None:
            continue
        if pane_id in live_ids:
            # Normalize parallel coder keys (coder_1, coder_2, ...) to "coder"
            base_role = role.split("_")[0] if role.startswith("coder_") else role
            active.add(base_role)
    return active


def load_state(state_path: Path) -> dict:
    try:
        text = state_path.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
    except Exception:
        pass
    return {}


def status_color(status: str) -> str:
    if status in ("completion_approved",):
        return GREEN
    if status in ("failed",):
        return RED
    if status in ("completion_pending", "review_ready"):
        return YELLOW
    return CYAN


def _trim_model(model: str, cli: str) -> str:
    """Strip vendor prefix matching CLI name, then truncate to 8 chars."""
    prefix = f"{cli}-"
    if model.lower().startswith(prefix.lower()):
        model = model[len(prefix) :]
    return model[:8]


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


def render(
    session_name: str,
    state_path: Path,
    panes_path: Path,
    agents: dict[str, dict[str, str]],
    width: int,
    height: int,
    start_time: float,
) -> str:
    state = load_state(state_path)
    active_roles = get_active_roles(session_name, panes_path)

    status = state.get("status", "waiting...")
    active_role = state.get("active_role", "")
    review_iter = state.get("review_iteration", 0)
    subplan_count = state.get("subplan_count", 0)

    lines: list[str] = []

    lines.append(f"{BOLD}{CYAN}Multi-Agent Pipeline{RESET}")
    lines.append("\u2500" * (width - 1))
    lines.append("")

    feature_request = _read_feature_request(state_path)
    if feature_request:
        lines.append(f"{BOLD}Feature{RESET}")
        max_feature_len = max(1, width - 4)
        if len(feature_request) > max_feature_len:
            feature_request = feature_request[: max_feature_len - 1] + "…"
        lines.append(f"  {DIM}{feature_request}{RESET}")
        lines.append("")
        lines.append("\u2500" * (width - 1))
        lines.append("")

    lines.append(f"{BOLD}Pipeline{RESET}")
    color = status_color(status)
    max_pipeline_len = max(1, width - 4)
    for pipeline_status in PIPELINE_STATES:
        display = pipeline_status[:max_pipeline_len]
        if pipeline_status == status:
            lines.append(f"  {color}\u25ba {display}{RESET}")
        else:
            lines.append(f"  {DIM}{display}{RESET}")

    if status not in PIPELINE_STATES:
        unknown_display = status[:max_pipeline_len]
        lines.append(f"  {color}\u25ba {unknown_display}{RESET}")

    if review_iter:
        lines.append(f"  {DIM}review iter {review_iter}{RESET}")
    if subplan_count > 1:
        lines.append(f"  {DIM}{subplan_count} subplans{RESET}")

    lines.append("")
    lines.append("\u2500" * (width - 1))
    lines.append("")

    lines.append(f"{BOLD}Agents{RESET}")
    lines.append("")

    for role, cfg in agents.items():
        is_active = role in active_roles
        is_current = role == active_role

        if is_active and is_current:
            bullet = f"{GREEN}\u25cf{RESET}"
            state_label = f"{GREEN}WORKING{RESET}"
            name_part = f"{BOLD}{role:<10}{RESET}"
        elif is_active:
            bullet = f"{YELLOW}\u25cf{RESET}"
            state_label = f"{YELLOW}ACTIVE{RESET}"
            name_part = f"{role:<10}"
        else:
            bullet = f"{DIM}\u25cb{RESET}"
            state_label = f"{DIM}IDLE{RESET}"
            name_part = f"{role:<10}"
            name_part = f"{DIM}{name_part}{RESET}"
        lines.append(f"  {bullet} {name_part} {state_label}")

        cli = cfg.get("cli", "?")
        model = _trim_model(cfg.get("model", ""), cli)
        lines.append(f"    {DIM}{cli}/{model}{RESET}")
        lines.append("")

    elapsed_seconds = max(0, int(time.time() - start_time))
    hours = elapsed_seconds // 3600
    minutes = (elapsed_seconds % 3600) // 60
    seconds = elapsed_seconds % 60
    elapsed_str = f"{hours}:{minutes:02d}:{seconds:02d}"

    footer = ["\u2500" * (width - 1), f"{DIM}↑ {elapsed_str}{RESET}"]

    lines.extend(footer)

    while len(lines) < height - 1:
        lines.append("")

    return "\n".join(lines[:height])


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
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    feature_dir = Path(args.feature_dir)
    state_path = feature_dir / "state.json"
    panes_path = feature_dir / "panes.json"
    config_path = Path(args.config)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    agents: dict[str, dict[str, str]] = {}
    for role in ("architect", "coder", "designer", "docs"):
        if role in raw:
            agents[role] = {"cli": raw[role]["cli"], "model": raw[role].get("model", "")}

    start_time = time.time()
    status_log_path = feature_dir / "status_log.txt"
    prev_status: str | None = None

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            width, height = get_terminal_size()
            output = render(args.session_name, state_path, panes_path, agents, width, height, start_time)
            sys.stdout.write("\033[H\033[2J" + output)
            sys.stdout.flush()
            state = load_state(state_path)
            prev_status = append_status_change(status_log_path, prev_status, state.get("status", ""))
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
