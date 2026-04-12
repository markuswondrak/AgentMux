from __future__ import annotations

import shlex
import sys
from pathlib import Path

from ..shared.models import AgentConfig
from ..terminal_ui.layout import MONITOR_MAX_WIDTH, MONITOR_MIN_WIDTH
from .command_builder import build_agent_command
from .content_zone import (
    ContentZone,
    _enforce_monitor_min_width,
    _find_any_hidden_pane,
    _find_pane_by_title,
    _pane_in_window,
    _park_to_hidden,
    _set_placeholder_id,
    set_pane_identity,
)
from .pane_io import accept_trust_prompt, send_prompt, send_text
from .tmux_core import MAIN_WINDOW, _log, run_command, tmux_pane_exists

__all__ = [
    "ContentZone",
    "_find_pane_by_title",
    "create_agent_pane",
    "create_batch_agent_pane",
    "create_completion_pane",
    "kill_agent_pane",
    "kill_agentmux_session",
    "send_prompt",
    "send_text",
    "set_pane_identity",
    "tmux_kill_session",
    "tmux_new_session",
    "tmux_pane_exists",
]


def tmux_new_session(
    session_name: str,
    agents: dict[str, AgentConfig],
    feature_dir: Path,
    project_dir: Path,
    config_path: Path | None,
    trust_snippet: str | None,
    primary_role: str = "architect",
) -> tuple[dict[str, str | None], ContentZone]:
    """Create the tmux session with control pane + primary agent pane."""
    monitor_cmd = (
        f"{shlex.quote(sys.executable)} -m agentmux.monitor"
        f" --feature-dir {shlex.quote(str(feature_dir))}"
        f" --session-name {shlex.quote(session_name)}"
    )
    if config_path is not None:
        monitor_cmd += f" --config {shlex.quote(str(config_path))}"

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
            "-c",
            str(project_dir),
            "-P",
            "-F",
            "#{pane_id}",
            monitor_cmd,
        ]
    )
    control_pane = result.stdout.strip()
    run_command(["tmux", "set-option", "-t", session_name, "pane-border-status", "top"])
    run_command(["tmux", "set-option", "-t", session_name, "pane-border-style", "none"])
    run_command(
        [
            "tmux",
            "set-option",
            "-t",
            session_name,
            "pane-active-border-style",
            "none",
        ]
    )
    run_command(
        [
            "tmux",
            "set-option",
            "-t",
            session_name,
            "pane-border-format",
            (
                "#{?#{@pane_label},"
                " #[bold]#{@pane_label}#[default],"
                "#{?#{@role},"
                " #[bold]#{@role}#[default],"
                "}}"
            ),
        ]
    )
    run_command(["tmux", "set-option", "-t", session_name, "allow-rename", "off"])
    run_command(["tmux", "select-pane", "-t", control_pane, "-T", ""])
    run_command(["tmux", "set-option", "-p", "-t", control_pane, "@role", ""])
    run_command(["tmux", "set-option", "-p", "-t", control_pane, "@pane_label", ""])
    run_command(
        ["tmux", "set-option", "-p", "-t", control_pane, "allow-passthrough", "on"],
        check=False,
    )
    run_command(
        ["tmux", "set-option", "-p", "-t", control_pane, "remain-on-exit", "on"],
        check=False,
    )
    run_command(
        ["tmux", "set-environment", "-t", session_name, "CONTROL_PANE", control_pane]
    )

    # Create primary pane (right side)
    primary_agent = agents[primary_role]
    primary_cmd = build_agent_command(primary_agent)
    result = run_command(
        [
            "tmux",
            "split-window",
            "-h",
            "-t",
            control_pane,
            "-c",
            str(project_dir),
            "-P",
            "-F",
            "#{pane_id}",
            primary_cmd,
        ]
    )
    primary_pane = result.stdout.strip()
    set_pane_identity(primary_pane, role=primary_role)

    # Create placeholder pane to keep the right zone permanently occupied.
    # It lives in _hidden and is swapped in whenever all agents are parked.
    result = run_command(
        [
            "tmux",
            "split-window",
            "-v",
            "-t",
            primary_pane,
            "-P",
            "-F",
            "#{pane_id}",
            "sleep infinity",
        ]
    )
    placeholder_pane = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", placeholder_pane, "-T", "placeholder"])
    run_command(["tmux", "set-option", "-p", "-t", placeholder_pane, "@role", ""])
    run_command(["tmux", "set-option", "-p", "-t", placeholder_pane, "@pane_label", ""])
    _park_to_hidden(placeholder_pane)
    _set_placeholder_id(session_name, placeholder_pane)

    _log(
        f"tmux_new_session: enforcing monitor width {MONITOR_MIN_WIDTH}-"
        f"{MONITOR_MAX_WIDTH}"
    )
    _enforce_monitor_min_width(session_name)
    accept_trust_prompt(primary_pane, snippet=trust_snippet)

    panes: dict[str, str | None] = {
        "_control": control_pane,
        primary_role: primary_pane,
    }
    # Initialize slots for other agents (created lazily)
    for role in agents:
        if role != primary_role:
            panes[role] = None

    return panes, ContentZone(
        session_name,
        visible=[primary_pane],
        placeholder=placeholder_pane,
    )


def _spawn_hidden_pane(
    session_name: str,
    project_dir: Path,
    cmd: str,
    *,
    label: str = "",
) -> tuple[str, int]:
    """Split a new pane from a hidden anchor, park it, and return (pane_id, pid)."""
    split_target = _find_any_hidden_pane(session_name)
    if not split_target:
        raise RuntimeError(
            f"No pane available to seed hidden pane creation for {session_name}"
        )
    _log(f"_spawn_hidden_pane: starting {label!r} at {split_target}")
    _log(f"_spawn_hidden_pane: command: {cmd}")
    result = run_command(
        [
            "tmux",
            "split-window",
            "-v",
            "-t",
            split_target,
            "-c",
            str(project_dir),
            "-P",
            "-F",
            "#{pane_id} #{pane_pid}",
            cmd,
        ]
    )
    parts = result.stdout.strip().split()
    pane_id = parts[0]
    pid = int(parts[1]) if len(parts) > 1 else 0
    if _pane_in_window(pane_id, MAIN_WINDOW):
        _park_to_hidden(pane_id)
    return pane_id, pid


def create_agent_pane(
    session_name: str,
    agent_name: str,
    agents: dict[str, AgentConfig],
    project_dir: Path,
    trust_snippet: str | None,
    *,
    display_label: str | None = None,
) -> tuple[str, int]:
    """Create a new agent pane and leave it parked in the hidden window.

    Returns:
        Tuple of (pane_id, process_pid)
    """
    agent = agents[agent_name]
    pane_id, pid = _spawn_hidden_pane(
        session_name, project_dir, build_agent_command(agent), label=agent_name
    )
    set_pane_identity(pane_id, role=agent.role, display_label=display_label)
    accept_trust_prompt(pane_id, snippet=trust_snippet)
    return pane_id, pid


def create_batch_agent_pane(
    session_name: str,
    agent_name: str,
    agents: dict[str, AgentConfig],
    prompt_file: str,
    project_dir: Path,
    *,
    display_label: str | None = None,
    output_log_path: Path | None = None,
) -> tuple[str, int]:
    """Create a batch-mode agent pane with prompt file reference.

    For batch mode (e.g., researcher agents), the prompt file path is passed
    as a command argument. The agent reads the file to get its instructions.
    This prevents shell argument length issues and is more robust.

    Args:
        output_log_path: Optional path to capture stderr output
            (contains both normal output and errors)
        project_dir: The project directory to use as working directory

    Returns:
        Tuple of (pane_id, process_pid)
    """
    agent = agents[agent_name]
    agent_cmd = build_agent_command(agent, prompt_file)
    if output_log_path:
        output_log_path.parent.mkdir(parents=True, exist_ok=True)
        agent_cmd += f" 2>{shlex.quote(str(output_log_path))}"
        _log(f"create_batch_agent_pane: stderr will be captured to {output_log_path}")

    pane_id, pid = _spawn_hidden_pane(
        session_name, project_dir, agent_cmd, label=agent_name
    )
    set_pane_identity(pane_id, role=agent.role, display_label=display_label)
    # No trust prompt handling needed for batch mode
    return pane_id, pid


def create_completion_pane(
    session_name: str,
    feature_dir: Path,
    project_dir: Path,
) -> tuple[str, int]:
    """Create a native completion-UI pane in the hidden window.

    The pane runs ``python -m agentmux.terminal_ui.completion_ui`` so the
    user sees the Rich-formatted confirmation screen without an AI agent.

    Returns:
        Tuple of (pane_id, process_pid)
    """
    completion_cmd = (
        f"{shlex.quote(sys.executable)} -m agentmux.terminal_ui.completion_ui"
        f" --feature-dir {shlex.quote(str(feature_dir))}"
        f" --project-dir {shlex.quote(str(project_dir))}"
    )
    pane_id, pid = _spawn_hidden_pane(
        session_name, project_dir, completion_cmd, label="completion"
    )
    set_pane_identity(pane_id, role="completion", display_label="Confirmation")
    return pane_id, pid


def kill_agent_pane(pane_id: str | None, session_name: str | None = None) -> None:
    """Kill a pane permanently (used for parallel coder cleanup)."""
    if not pane_id:
        return
    _log(f"kill_agent_pane: Killing pane {pane_id}")
    run_command(["tmux", "kill-pane", "-t", pane_id], check=False)


def tmux_kill_session(session_name: str) -> None:
    run_command(["tmux", "kill-session", "-t", session_name], check=False)


def kill_agentmux_session(session_name: str) -> bool:
    """Kill a tmux session by name. Return True on success, False on failure."""
    result = run_command(["tmux", "kill-session", "-t", session_name], check=False)
    return result.returncode == 0
