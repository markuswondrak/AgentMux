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
            ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_id}"],
            capture_output=True, text=True, check=False,
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


def render(
    session_name: str,
    state_path: Path,
    panes_path: Path,
    agents: dict[str, dict[str, str]],
    width: int,
    height: int,
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

    lines.append(f"{BOLD}Pipeline{RESET}")
    color = status_color(status)
    lines.append(f"  {color}{status}{RESET}")

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
        if is_active:
            bullet = f"{GREEN}\u25cf{RESET}"
            state_label = f"{GREEN}ACTIVE{RESET}"
        else:
            bullet = f"{DIM}\u25cb{RESET}"
            state_label = f"{DIM}IDLE{RESET}"

        is_current = role == active_role
        name_part = f"{BOLD}{role}{RESET}" if is_current else role
        lines.append(f"  {bullet} {name_part:<12} {state_label}")

        cli = cfg.get("cli", "?")
        model = cfg.get("model", "")
        if len(model) > 14:
            model = model[:14]
        lines.append(f"    {DIM}{cli} / {model}{RESET}")
        lines.append("")

    lines.append("\u2500" * (width - 1))
    ts = time.strftime("%H:%M:%S")
    lines.append(f"{DIM}{ts}{RESET}")

    while len(lines) < height - 1:
        lines.append("")

    return "\n".join(lines[:height])


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

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            width, height = get_terminal_size()
            output = render(args.session_name, state_path, panes_path, agents, width, height)
            sys.stdout.write("\033[H\033[2J" + output)
            sys.stdout.flush()
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
