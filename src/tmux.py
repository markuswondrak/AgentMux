from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path

from .models import AgentConfig

TRUST_PROMPT_SNIPPET = "Do you trust the contents of this directory?"
CONTROL_PANE_WIDTH = 20
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


def build_agent_command(agent: AgentConfig) -> str:
    extra_args = " ".join(shlex.quote(a) for a in (agent.args or []))
    return f"{shlex.quote(agent.cli)} --model {shlex.quote(agent.model)}" + (
        f" {extra_args}" if extra_args else ""
    )


def tmux_session_exists(session_name: str) -> bool:
    result = run_command(["tmux", "has-session", "-t", session_name], check=False)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    """Print debug message to stdout (captured in orchestrator log)."""
    print(f"[TMUX DEBUG] {msg}")


def _log_layout(session_name: str) -> None:
    """Log current window layout and main-pane-width."""
    # Get window layout
    layout_result = run_command(
        ["tmux", "display-message", "-p", "-t", f"{session_name}:{MAIN_WINDOW}", "#{window_layout}"],
        check=False,
    )
    layout = layout_result.stdout.strip() if layout_result.returncode == 0 else "(error)"

    # Get main-pane-width
    width_result = run_command(
        ["tmux", "show-option", "-t", f"{session_name}:{MAIN_WINDOW}", "main-pane-width"],
        check=False,
    )
    width = width_result.stdout.strip() if width_result.returncode == 0 else "(error)"

    # List panes with widths
    panes_result = run_command(
        ["tmux", "list-panes", "-t", f"{session_name}:{MAIN_WINDOW}", "-F", "#{pane_id} #{pane_title} W=#{pane_width}"],
        check=False,
    )
    panes = panes_result.stdout.strip() if panes_result.returncode == 0 else "(error)"

    _log(f"Layout: {layout}")
    _log(f"main-pane-width: {width}")
    _log(f"Panes: {panes}")


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _find_control_pane(session_name: str) -> str | None:
    """Return the pane ID of the control pane (titled 'control'), or None."""
    result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "-F",
            "#{pane_id} #{pane_title}",
        ],
        check=False,
    )
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1] == "control":
            return parts[0]
    return None


def _reapply_layout(session_name: str) -> None:
    """Reapply main-vertical layout so the monitor pane is always CONTROL_PANE_WIDTH cols.

    tmux's main-vertical layout keeps the leftmost (main) pane at exactly
    main-pane-width columns, regardless of any join-pane / break-pane operations.
    Calling this after every pane change re-enforces the fixed width.
    """
    _log(f"_reapply_layout: Before select-layout")
    _log_layout(session_name)

    run_command(
        [
            "tmux",
            "select-layout",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "main-vertical",
        ],
        check=False,
    )

    _log(f"_reapply_layout: After select-layout")
    _log_layout(session_name)


def _is_pane_visible(pane_id: str | None, session_name: str) -> bool:
    """Check if a pane is in the main window (not hidden)."""
    if not pane_id:
        return False
    result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "-F",
            "#{pane_id}",
        ],
        check=False,
    )
    return pane_id in result.stdout


def _park_all_agents(session_name: str) -> None:
    """Move all non-control panes from the main window into _hidden."""
    result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "-F",
            "#{pane_id} #{pane_title}",
        ],
        check=False,
    )
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1] != "control":
            run_command(
                [
                    "tmux",
                    "break-pane",
                    "-d",
                    "-s",
                    parts[0],
                    "-n",
                    "_hidden",
                ],
                check=False,
            )


# ---------------------------------------------------------------------------
# Pane lifecycle: park / show
# ---------------------------------------------------------------------------


def park_agent_pane(pane_id: str | None, session_name: str) -> None:
    """Move a pane to the hidden window. Process keeps running."""
    if not pane_id:
        return
    if not _is_pane_visible(pane_id, session_name):
        return
    _log(f"park_agent_pane: Breaking pane {pane_id}")
    run_command(
        ["tmux", "break-pane", "-d", "-s", pane_id, "-n", "_hidden"], check=False
    )
    _reapply_layout(session_name)


def show_agent_pane(
    pane_id: str | None, session_name: str, *, exclusive: bool = True
) -> None:
    """Join a pane into the main window.

    If exclusive=True (default), park all other agent panes first so only
    this agent is visible. Set exclusive=False for parallel mode.
    """
    if not pane_id:
        return
    if _is_pane_visible(pane_id, session_name):
        return
    _log(f"show_agent_pane: Joining pane {pane_id} (exclusive={exclusive})")
    if exclusive:
        _park_all_agents(session_name)
    # Join horizontally next to control if no agent panes visible,
    # otherwise vertically to stack with other agents
    target = _find_agent_pane_in_main(session_name)
    control = _find_control_pane(session_name)
    if target == f"{session_name}:{MAIN_WINDOW}" or target == control:
        # No agent panes visible — join horizontally next to control
        _log(f"show_agent_pane: join-pane -h to control {control}")
        run_command(
            ["tmux", "join-pane", "-h", "-s", pane_id, "-t", control], check=False
        )
    else:
        # Stack vertically with existing agent panes
        _log(f"show_agent_pane: join-pane -v to agent {target}")
        run_command(
            ["tmux", "join-pane", "-v", "-s", pane_id, "-t", target], check=False
        )
    _reapply_layout(session_name)


# ---------------------------------------------------------------------------
# Session and pane creation
# ---------------------------------------------------------------------------


def tmux_new_session(
    session_name: str,
    agents: dict[str, AgentConfig],
    feature_dir: Path,
    config_path: Path,
) -> dict[str, str | None]:
    """Create the tmux session with control pane + architect pane.

    Other agents are created lazily on first send_prompt via _ensure_agent_pane.
    """
    monitor_script = Path(__file__).resolve().parent / "monitor.py"
    monitor_cmd = (
        f"python3 {shlex.quote(str(monitor_script))}"
        f" --feature-dir {shlex.quote(str(feature_dir))}"
        f" --session-name {shlex.quote(session_name)}"
        f" --config {shlex.quote(str(config_path))}"
    )

    # Create session with control pane (left)
    result = run_command(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            MAIN_WINDOW,
            "-P",
            "-F",
            "#{pane_id}",
            monitor_cmd,
        ]
    )
    control_pane = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", control_pane, "-T", "control"])

    # Fix the monitor pane width permanently via tmux's layout engine
    _log(f"tmux_new_session: Setting main-pane-width to {CONTROL_PANE_WIDTH}")
    run_command([
        "tmux", "set-option", "-t", f"{session_name}:{MAIN_WINDOW}",
        "main-pane-width", str(CONTROL_PANE_WIDTH),
    ])
    _log_layout(session_name)

    # Create architect pane (right side)
    architect = agents["architect"]
    architect_cmd = build_agent_command(architect)
    result = run_command(
        [
            "tmux",
            "split-window",
            "-h",
            "-t",
            control_pane,
            "-P",
            "-F",
            "#{pane_id}",
            architect_cmd,
        ]
    )
    architect_pane = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", architect_pane, "-T", "architect"])

    _reapply_layout(session_name)
    accept_trust_prompt(architect_pane)

    panes: dict[str, str | None] = {
        "_control": control_pane,
        "architect": architect_pane,
    }
    # Initialize slots for other agents (created lazily)
    for role in agents:
        if role != "architect":
            panes[role] = None

    return panes


def _find_agent_pane_in_main(session_name: str) -> str:
    """Find a non-control pane in the main window to split from."""
    result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "-F",
            "#{pane_id} #{pane_title}",
        ]
    )
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        title = parts[1] if len(parts) == 2 else ""
        if title != "control":
            return parts[0]
    return f"{session_name}:{MAIN_WINDOW}"


def create_agent_pane(
    session_name: str, agent_name: str, agents: dict[str, AgentConfig]
) -> str:
    """Create a new agent pane. Used for lazy creation and parallel coders."""
    agent = agents[agent_name]
    agent_cmd = build_agent_command(agent)
    split_target = _find_agent_pane_in_main(session_name)
    control = _find_control_pane(session_name)
    # If no agent pane is visible, split horizontally from control
    if split_target == f"{session_name}:{MAIN_WINDOW}" or split_target == control:
        split_dir = "-h"
        split_target = control or f"{session_name}:{MAIN_WINDOW}"
    else:
        split_dir = "-v"
    _log(f"create_agent_pane: Creating {agent_name} with split-window {split_dir} at {split_target}")
    result = run_command(
        [
            "tmux",
            "split-window",
            split_dir,
            "-t",
            split_target,
            "-P",
            "-F",
            "#{pane_id}",
            agent_cmd,
        ]
    )
    pane_id = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", pane_id, "-T", agent.role])
    _reapply_layout(session_name)
    accept_trust_prompt(pane_id)
    return pane_id


def kill_agent_pane(pane_id: str | None, session_name: str | None = None) -> None:
    """Kill a pane permanently (used for parallel coder cleanup)."""
    if not pane_id:
        return
    _log(f"kill_agent_pane: Killing pane {pane_id}")
    run_command(["tmux", "kill-pane", "-t", pane_id], check=False)
    if session_name:
        _reapply_layout(session_name)


def tmux_kill_session(session_name: str) -> None:
    run_command(["tmux", "kill-session", "-t", session_name], check=False)


# ---------------------------------------------------------------------------
# Pane interaction
# ---------------------------------------------------------------------------


def capture_pane(target_pane: str, history_lines: int = 160) -> str:
    result = run_command(
        ["tmux", "capture-pane", "-p", "-S", f"-{history_lines}", "-t", target_pane]
    )
    return result.stdout


def tmux_pane_exists(target_pane: str | None) -> bool:
    if not target_pane:
        return False
    result = run_command(
        ["tmux", "display-message", "-p", "-t", target_pane, "#{pane_id}"],
        check=False,
    )
    return result.returncode == 0


def send_text(target_pane: str, text: str) -> None:
    # select-window first so the attached client visually switches to the right pane
    if ":" in target_pane:
        session_window = target_pane.rsplit(".", 1)[0]
        run_command(["tmux", "select-window", "-t", session_window])
    run_command(["tmux", "select-pane", "-t", target_pane])
    run_command(["tmux", "send-keys", "-t", target_pane, "-l", text])
    time.sleep(3.0)
    run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])
    time.sleep(0.5)
    run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])


def normalize_prompt(content: str) -> str:
    # Interactive CLIs commonly keep pasted multi-line content as a draft.
    # Sending a single line makes Enter behave like a real submit.
    return re.sub(r"\s+", " ", content).strip()


def send_prompt(
    target_pane: str | None,
    prompt_file: Path,
    session_name: str | None = None,
    *,
    role: str | None = None,
    agents: dict[str, AgentConfig] | None = None,
    panes: dict[str, str | None] | None = None,
) -> None:
    """Send a prompt to a pane. If session_name is given, auto-show the pane first.

    If target_pane is None and role/agents/panes are provided, the agent pane
    is created lazily (first use).
    """
    if target_pane is None and role and agents and panes and session_name:
        target_pane = _ensure_agent_pane(session_name, role, agents, panes)
    if not target_pane or not tmux_pane_exists(target_pane):
        return
    if session_name:
        show_agent_pane(target_pane, session_name)
    prompt = normalize_prompt(prompt_file.read_text(encoding="utf-8"))
    send_text(target_pane, prompt)


def _ensure_agent_pane(
    session_name: str,
    role: str,
    agents: dict[str, AgentConfig],
    panes: dict[str, str | None],
) -> str | None:
    """Create an agent pane if it doesn't exist yet. Returns the pane ID."""
    if panes.get(role) and tmux_pane_exists(panes[role]):
        return panes[role]
    if role not in agents:
        return None
    pane_id = create_agent_pane(session_name, role, agents)
    # Immediately park it — show_agent_pane will bring it back
    park_agent_pane(pane_id, session_name)
    panes[role] = pane_id
    return pane_id


def accept_trust_prompt(target_pane: str, timeout_seconds: float = 3.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if TRUST_PROMPT_SNIPPET in capture_pane(target_pane):
            run_command(["tmux", "select-pane", "-t", target_pane])
            run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])
            return
        time.sleep(0.2)
