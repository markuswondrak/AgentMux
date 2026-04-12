from __future__ import annotations

import time
from pathlib import Path

from .tmux_core import _log, capture_pane, run_command, tmux_pane_exists


def _wait_for_pane_ready(target_pane: str, timeout: float = 20.0) -> None:
    """Poll pane content until the agent TUI has rendered stable, non-empty output."""
    deadline = time.time() + timeout
    prev_content = ""
    stable_count = 0
    while time.time() < deadline:
        content = capture_pane(target_pane).strip()
        if content and len(content) > 20:
            if content == prev_content:
                stable_count += 1
                if stable_count >= 2:
                    _log(f"_wait_for_pane_ready: {target_pane} ready")
                    return
            else:
                stable_count = 0
            prev_content = content
        time.sleep(0.5)
    _log(f"_wait_for_pane_ready: {target_pane} timed out after {timeout}s")


def send_text(target_pane: str, text: str) -> None:
    if not tmux_pane_exists(target_pane):
        _log(f"send_text: pane {target_pane} does not exist, skipping")
        return
    _wait_for_pane_ready(target_pane)
    # select-window first so the attached client visually switches to the right pane
    if ":" in target_pane:
        session_window = target_pane.rsplit(".", 1)[0]
        run_command(["tmux", "select-window", "-t", session_window], check=False)
    run_command(["tmux", "select-pane", "-t", target_pane], check=False)
    run_command(["tmux", "send-keys", "-t", target_pane, "-l", text], check=False)
    time.sleep(3.0)
    # Single Enter to submit.
    run_command(["tmux", "send-keys", "-t", target_pane, "Enter"], check=False)


def send_prompt(
    target_pane: str | None,
    prompt_file: Path,
    *,
    prefix_command: str | None = None,
) -> None:
    """Send a prompt reference message to an existing pane.

    If prefix_command is provided, it is sent as keystrokes BEFORE the
    prompt file reference. This is needed for CLI slash commands (e.g.
    /fleet for Copilot) that must be entered interactively to be recognized.
    """
    if not target_pane or not tmux_pane_exists(target_pane):
        return
    if prefix_command:
        send_text(target_pane, prefix_command)
        time.sleep(1.0)
    prompt_reference = f"Read and follow the instructions in {prompt_file.resolve()}"
    send_text(target_pane, prompt_reference)


def accept_trust_prompt(
    target_pane: str,
    *,
    snippet: str | None,
    timeout_seconds: float = 3.0,
) -> None:
    if snippet is None:
        return
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if snippet in capture_pane(target_pane):
            run_command(["tmux", "select-pane", "-t", target_pane])
            run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])
            break
        time.sleep(0.2)
    time.sleep(0.5)  # let the CLI tool finish starting up before sending keys
