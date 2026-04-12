from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

MAIN_WINDOW = "pipeline"


def run_command(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=True,
    )


def tmux_session_exists(session_name: str) -> bool:
    result = run_command(["tmux", "has-session", "-t", session_name], check=False)
    return result.returncode == 0


def list_agentmux_sessions() -> list[str]:
    """Return names of active tmux sessions starting with ``agentmux-``."""
    try:
        result = run_command(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            check=False,
        )
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt):
        return []
    if result is None or not hasattr(result, "returncode"):
        return []
    if result.returncode != 0:
        return []
    return [
        name.strip()
        for name in result.stdout.splitlines()
        if name.strip().startswith("agentmux-")
    ]


def _log(msg: str) -> None:
    """Print debug message to stdout (captured in orchestrator log)."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[TMUX DEBUG {ts}] {msg}")


def tmux_pane_exists(target_pane: str | None) -> bool:
    if not target_pane:
        return False
    result = run_command(
        ["tmux", "display-message", "-p", "-t", target_pane, "#{pane_id} #{pane_dead}"],
        check=False,
    )
    if result.returncode != 0:
        return False
    parts = result.stdout.strip().split()
    if len(parts) < 2:
        return False
    return parts[1] != "1"


def capture_pane(target_pane: str, history_lines: int = 160) -> str:
    result = run_command(
        ["tmux", "capture-pane", "-p", "-S", f"-{history_lines}", "-t", target_pane],
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout
