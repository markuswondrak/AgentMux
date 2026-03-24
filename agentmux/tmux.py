from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from .models import AgentConfig

CONTROL_PANE_WIDTH = 15
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
    return f"{shlex.quote(agent.cli)} {shlex.quote(agent.model_flag)} {shlex.quote(agent.model)}" + (
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
        [
            "tmux",
            "display-message",
            "-p",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "#{window_layout}",
        ],
        check=False,
    )
    layout = (
        layout_result.stdout.strip() if layout_result.returncode == 0 else "(error)"
    )

    # List panes with widths
    panes_result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "-F",
            "#{pane_id} #{pane_title} W=#{pane_width}",
        ],
        check=False,
    )
    panes = panes_result.stdout.strip() if panes_result.returncode == 0 else "(error)"

    _log(f"Layout: {layout}")
    _log(f"Panes: {panes}")


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _find_control_pane(session_name: str) -> str | None:
    """Return the pane ID of the control pane, stored in the session environment."""
    result = run_command(
        ["tmux", "show-environment", "-t", session_name, "CONTROL_PANE"],
        check=False,
    )
    if result.returncode == 0 and "=" in result.stdout:
        return result.stdout.strip().split("=", 1)[1]
    return None


def _get_placeholder_id(session_name: str) -> str | None:
    """Get placeholder pane ID from tmux session environment."""
    result = run_command(
        ["tmux", "show-environment", "-t", session_name, "PLACEHOLDER_PANE"],
        check=False,
    )
    if result.returncode == 0 and "=" in result.stdout:
        return result.stdout.strip().split("=", 1)[1]
    return None


def _set_placeholder_id(session_name: str, pane_id: str) -> None:
    """Store placeholder pane ID in tmux session environment."""
    run_command(
        ["tmux", "set-environment", "-t", session_name, "PLACEHOLDER_PANE", pane_id],
        check=False,
    )


def _find_pane_by_title(session_name: str, title: str) -> str | None:
    """Find any pane in the session (all windows) with the given @role."""
    for window in [MAIN_WINDOW, "_hidden"]:
        result = run_command(
            [
                "tmux",
                "list-panes",
                "-t",
                f"{session_name}:{window}",
                "-F",
                "#{pane_id} #{@role}",
            ],
            check=False,
        )
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[1] == title:
                return parts[0]
    return None


def _list_agent_panes_in_main(session_name: str) -> list[str]:
    """Return pane IDs of all non-control panes in the main window (right zone)."""
    result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{MAIN_WINDOW}",
            "-F",
            "#{pane_id} #{@role}",
        ],
        check=False,
    )
    panes = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1]:
            panes.append(parts[0])
    return panes


def _fix_control_width(session_name: str) -> None:
    """One-shot resize of the control pane. Only needed after join-pane -h."""
    control = _find_control_pane(session_name)
    if control:
        _log(f"_fix_control_width: resizing {control} to {CONTROL_PANE_WIDTH}")
        run_command(
            ["tmux", "resize-pane", "-t", control, "-x", str(CONTROL_PANE_WIDTH)],
            check=False,
        )
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


# ---------------------------------------------------------------------------
# Pane lifecycle: park / show
# ---------------------------------------------------------------------------


def park_agent_pane(pane_id: str | None, session_name: str) -> None:
    """Move a pane to the hidden window. Process keeps running.

    If this is the last pane in the right zone, swaps with the placeholder pane
    instead of breaking, so the right zone is never left empty.
    """
    if not pane_id:
        return
    if not _is_pane_visible(pane_id, session_name):
        return
    right_zone = _list_agent_panes_in_main(session_name)
    if right_zone == [pane_id]:
        placeholder = _get_placeholder_id(session_name)
        if not placeholder or not tmux_pane_exists(placeholder):
            _log(f"park_agent_pane: creating placeholder on-demand")
            result = run_command(
                [
                    "tmux", "split-window", "-v", "-t", pane_id,
                    "-P", "-F", "#{pane_id}", "sleep infinity",
                ],
                check=False,
            )
            placeholder = result.stdout.strip() if result.returncode == 0 else None
            if placeholder:
                run_command(["tmux", "set-option", "-p", "-t", placeholder, "@role", ""])
                run_command(
                    ["tmux", "break-pane", "-d", "-s", placeholder, "-n", "_hidden"],
                    check=False,
                )
                _set_placeholder_id(session_name, placeholder)
        if placeholder and not _is_pane_visible(placeholder, session_name):
            _log(f"park_agent_pane: swap placeholder {placeholder} ↔ {pane_id}")
            run_command(
                ["tmux", "swap-pane", "-s", placeholder, "-t", pane_id], check=False
            )
            return
    _log(f"park_agent_pane: Breaking pane {pane_id}")
    run_command(
        ["tmux", "break-pane", "-d", "-s", pane_id, "-n", "_hidden"], check=False
    )


def show_agent_pane(
    pane_id: str | None, session_name: str, *, exclusive: bool = True
) -> None:
    """Join a pane into the main window.

    If exclusive=True (default), park all other agent panes first so only
    this agent is visible. Set exclusive=False for parallel mode.

    Uses swap-pane for exclusive replacement to avoid touching the
    horizontal partition between monitor and agent zone.
    """
    if not pane_id:
        return
    if _is_pane_visible(pane_id, session_name):
        return
    _log(f"show_agent_pane: Showing pane {pane_id} (exclusive={exclusive})")

    right_zone = _list_agent_panes_in_main(session_name)

    if exclusive and right_zone:
        # Park extras, then swap with the remaining one
        keep = right_zone[0]
        for other in right_zone[1:]:
            _log(f"show_agent_pane: parking extra {other}")
            run_command(
                ["tmux", "break-pane", "-d", "-s", other, "-n", "_hidden"],
                check=False,
            )
        _log(f"show_agent_pane: swap-pane -s {pane_id} -t {keep}")
        run_command(["tmux", "swap-pane", "-s", pane_id, "-t", keep], check=False)
    elif not exclusive and right_zone:
        # Stack vertically with existing agent panes
        _log(f"show_agent_pane: join-pane -v -s {pane_id} -t {right_zone[0]}")
        run_command(
            ["tmux", "join-pane", "-v", "-s", pane_id, "-t", right_zone[0]],
            check=False,
        )
    else:
        # Right zone empty — fallback: horizontal join + one-time width fix
        control = _find_control_pane(session_name)
        _log(f"show_agent_pane: join-pane -h -s {pane_id} -t {control} (fallback)")
        run_command(
            ["tmux", "join-pane", "-h", "-s", pane_id, "-t", control], check=False
        )
        _fix_control_width(session_name)

    _log_layout(session_name)


# ---------------------------------------------------------------------------
# Session and pane creation
# ---------------------------------------------------------------------------


def tmux_new_session(
    session_name: str,
    agents: dict[str, AgentConfig],
    feature_dir: Path,
    config_path: Path | None,
    trust_snippet: str | None,
    primary_role: str = "architect",
) -> dict[str, str | None]:
    """Create the tmux session with control pane + primary agent pane.

    Other agents are created lazily on first send_prompt via _ensure_agent_pane.
    """
    project_root = Path(__file__).resolve().parent.parent
    monitor_cmd = (
        f"cd {shlex.quote(str(project_root))} && "
        f"python3 -m agentmux.monitor"
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
            "-P",
            "-F",
            "#{pane_id}",
            monitor_cmd,
        ]
    )
    control_pane = result.stdout.strip()
    feature_slug = feature_dir.name
    run_command(["tmux", "set-option", "-t", session_name, "pane-border-status", "top"])
    run_command(["tmux", "set-option", "-t", session_name, "pane-border-format",
                 f"#{{?#{{@role}},,"
                 f" #[bold]#{{@role}}#[nobold]"
                 f" #[dim]· {feature_slug}#[default] }}"])
    run_command(["tmux", "set-option", "-t", session_name, "allow-rename", "off"])
    run_command(["tmux", "select-pane", "-t", control_pane, "-T", ""])
    run_command(["tmux", "set-option", "-p", "-t", control_pane, "@role", ""])
    run_command(["tmux", "set-environment", "-t", session_name, "CONTROL_PANE", control_pane])

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
            "-P",
            "-F",
            "#{pane_id}",
            primary_cmd,
        ]
    )
    primary_pane = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", primary_pane, "-T", primary_role])
    run_command(["tmux", "set-option", "-p", "-t", primary_pane, "@role", primary_role])

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
    run_command(
        ["tmux", "break-pane", "-d", "-s", placeholder_pane, "-n", "_hidden"],
        check=False,
    )
    _set_placeholder_id(session_name, placeholder_pane)

    # Set control pane width ONCE — never touched again programmatically
    _log(f"tmux_new_session: Setting control width to {CONTROL_PANE_WIDTH}")
    _fix_control_width(session_name)
    accept_trust_prompt(primary_pane, snippet=trust_snippet)

    panes: dict[str, str | None] = {
        "_control": control_pane,
        primary_role: primary_pane,
    }
    # Initialize slots for other agents (created lazily)
    for role in agents:
        if role != primary_role:
            panes[role] = None

    return panes


def create_agent_pane(
    session_name: str,
    agent_name: str,
    agents: dict[str, AgentConfig],
    trust_snippet: str | None,
) -> str:
    """Create a new agent pane. Used for lazy creation and parallel coders."""
    agent = agents[agent_name]
    agent_cmd = build_agent_command(agent)
    right_zone = _list_agent_panes_in_main(session_name)

    if right_zone:
        split_dir = "-v"
        split_target = right_zone[0]
    else:
        split_dir = "-h"
        split_target = (
            _find_control_pane(session_name) or f"{session_name}:{MAIN_WINDOW}"
        )

    _log(
        f"create_agent_pane: Creating {agent_name} with split-window {split_dir} at {split_target}"
    )
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
    run_command(["tmux", "set-option", "-p", "-t", pane_id, "@role", agent.role])

    if not right_zone:
        # Was horizontal split — fix control width once
        _fix_control_width(session_name)

    accept_trust_prompt(pane_id, snippet=trust_snippet)
    time.sleep(0.5)  # let the CLI tool finish starting up before sending keys
    return pane_id


def kill_agent_pane(pane_id: str | None, session_name: str | None = None) -> None:
    """Kill a pane permanently (used for parallel coder cleanup)."""
    if not pane_id:
        return
    _log(f"kill_agent_pane: Killing pane {pane_id}")
    run_command(["tmux", "kill-pane", "-t", pane_id], check=False)


def tmux_kill_session(session_name: str) -> None:
    run_command(["tmux", "kill-session", "-t", session_name], check=False)


# ---------------------------------------------------------------------------
# Pane interaction
# ---------------------------------------------------------------------------


def capture_pane(target_pane: str, history_lines: int = 160) -> str:
    result = run_command(
        ["tmux", "capture-pane", "-p", "-S", f"-{history_lines}", "-t", target_pane],
        check=False,
    )
    if result.returncode != 0:
        return ""
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
    if not tmux_pane_exists(target_pane):
        _log(f"send_text: pane {target_pane} does not exist, skipping")
        return
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
    prompt_reference = f"Read and follow the instructions in {prompt_file.resolve()}"
    send_text(target_pane, prompt_reference)


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
    pane_id = create_agent_pane(session_name, role, agents, agents[role].trust_snippet)
    # Immediately park it — show_agent_pane will bring it back
    park_agent_pane(pane_id, session_name)
    panes[role] = pane_id
    return pane_id


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
            return
        time.sleep(0.2)
