from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from ..shared.models import AgentConfig
from ..terminal_ui.layout import MONITOR_MAX_WIDTH, MONITOR_MIN_WIDTH, MONITOR_WIDTH

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
    env_prefix = ""
    if agent.env:
        env_items = [f"{shlex.quote(str(key))}={shlex.quote(str(value))}" for key, value in agent.env.items()]
        env_prefix = f"env {' '.join(env_items)} "
    extra_args = " ".join(shlex.quote(a) for a in (agent.args or []))
    return env_prefix + f"{shlex.quote(agent.cli)} {shlex.quote(agent.model_flag)} {shlex.quote(agent.model)}" + (
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


def set_pane_identity(
    pane_id: str,
    *,
    role: str,
    display_label: str | None = None,
) -> None:
    visible_label = (display_label or role).strip()
    run_command(["tmux", "select-pane", "-t", pane_id, "-T", visible_label], check=False)
    run_command(["tmux", "set-option", "-p", "-t", pane_id, "@role", role], check=False)
    run_command(
        ["tmux", "set-option", "-p", "-t", pane_id, "@pane_label", (display_label or "").strip()],
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


def _list_window_panes(session_name: str, window_name: str) -> list[str]:
    result = run_command(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{session_name}:{window_name}",
            "-F",
            "#{pane_id}",
        ],
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _pane_in_window(pane_id: str | None, window_name: str) -> bool:
    if not pane_id:
        return False
    result = run_command(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{window_name}"],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == window_name


def _get_pane_width(pane_id: str | None) -> int | None:
    if not pane_id:
        return None
    result = run_command(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_width}"],
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _enforce_monitor_min_width(session_name: str) -> None:
    """Clamp the monitor pane width to the supported range."""
    control = _find_control_pane(session_name)
    if not control:
        return
    width = _get_pane_width(control)
    if width is None:
        return
    target_width: int | None = None
    if width < MONITOR_MIN_WIDTH:
        target_width = MONITOR_MIN_WIDTH
    elif width > MONITOR_MAX_WIDTH:
        target_width = MONITOR_MAX_WIDTH
    if target_width is None:
        return
    _log(f"_enforce_monitor_min_width: resizing {control} to {target_width}")
    run_command(
        ["tmux", "resize-pane", "-t", control, "-x", str(target_width)],
        check=False,
    )
    _log_layout(session_name)


def _enforce_monitor_width(session_name: str) -> None:
    """Backward-compatible alias for monitor width enforcement."""
    _enforce_monitor_min_width(session_name)


def _find_any_hidden_pane(session_name: str) -> str | None:
    for pane_id in _list_window_panes(session_name, "_hidden"):
        if tmux_pane_exists(pane_id):
            return pane_id
    placeholder = _get_placeholder_id(session_name)
    if placeholder and tmux_pane_exists(placeholder):
        return placeholder
    return None


# ---------------------------------------------------------------------------
# Pane lifecycle: content zone
# ---------------------------------------------------------------------------


class ContentZone:
    """Manage the content area right of the control pane.

    `_visible` is the single source of truth for which agent panes occupy the
    right zone. The placeholder pane is an internal implementation detail.
    """

    def __init__(
        self,
        session_name: str,
        *,
        visible: list[str] | None = None,
        placeholder: str | None = None,
    ) -> None:
        self._session = session_name
        self._visible: list[str] = []
        seen: set[str] = set()
        for pane_id in visible or []:
            if pane_id and pane_id not in seen:
                self._visible.append(pane_id)
                seen.add(pane_id)
        self._placeholder = placeholder or _get_placeholder_id(session_name)
        if self._placeholder and not tmux_pane_exists(self._placeholder):
            self._placeholder = None

    @property
    def visible(self) -> list[str]:
        return list(self._visible)

    def is_visible(self, pane_id: str) -> bool:
        return pane_id in self._visible

    def restore(self, known_panes: list[str]) -> None:
        desired = self._visible_from_snapshot(known_panes)
        current_visible: list[str] = []
        seen: set[str] = set()
        for pane_id in known_panes:
            if (
                pane_id
                and pane_id not in seen
                and tmux_pane_exists(pane_id)
                and _pane_in_window(pane_id, MAIN_WINDOW)
            ):
                current_visible.append(pane_id)
                seen.add(pane_id)
        self._visible = current_visible
        if desired:
            self.show_parallel(desired)
        else:
            self.hide_all()

    def show(self, pane_id: str) -> None:
        if not pane_id or not tmux_pane_exists(pane_id):
            return
        if self._visible == [pane_id]:
            return

        if not self._visible:
            placeholder = self._require_placeholder()
            if not placeholder:
                return
            _log(f"ContentZone.show: swap-pane -s {pane_id} -t {placeholder}")
            run_command(["tmux", "swap-pane", "-s", pane_id, "-t", placeholder], check=False)
        else:
            keep = pane_id if pane_id in self._visible else self._visible[-1]
            for other in list(self._visible):
                if other != keep:
                    self._park(other)
            if keep != pane_id:
                _log(f"ContentZone.show: swap-pane -s {pane_id} -t {keep}")
                run_command(["tmux", "swap-pane", "-s", pane_id, "-t", keep], check=False)

        self._visible = [pane_id]
        self._enforce_invariant()
        _enforce_monitor_min_width(self._session)
        _log_layout(self._session)

    def show_parallel(self, pane_ids: list[str]) -> None:
        ordered: list[str] = []
        seen: set[str] = set()
        for pane_id in pane_ids:
            if pane_id and pane_id not in seen and tmux_pane_exists(pane_id):
                ordered.append(pane_id)
                seen.add(pane_id)
        if not ordered:
            self.hide_all()
            return

        self.show(ordered[0])
        anchor = ordered[0]
        visible = [anchor]
        for pane_id in ordered[1:]:
            if pane_id == anchor:
                continue
            _log(f"ContentZone.show_parallel: join-pane -v -s {pane_id} -t {anchor}")
            run_command(
                ["tmux", "join-pane", "-v", "-s", pane_id, "-t", anchor],
                check=False,
            )
            visible.append(pane_id)

        self._visible = visible
        self._enforce_invariant()
        self._rebalance_visible_panes()
        _enforce_monitor_min_width(self._session)
        _log_layout(self._session)

    def hide(self, pane_id: str) -> None:
        if pane_id not in self._visible:
            return
        if len(self._visible) == 1:
            placeholder = self._require_placeholder()
            if not placeholder:
                return
            _log(f"ContentZone.hide: swap-pane -s {placeholder} -t {pane_id}")
            run_command(["tmux", "swap-pane", "-s", placeholder, "-t", pane_id], check=False)
            self._visible = []
        else:
            self._park(pane_id)
            self._visible = [current for current in self._visible if current != pane_id]

        self._enforce_invariant()
        self._rebalance_visible_panes()
        _enforce_monitor_min_width(self._session)
        _log_layout(self._session)

    def hide_all(self) -> None:
        if not self._visible:
            self._enforce_invariant()
            return

        keep = self._visible[-1]
        for pane_id in list(self._visible[:-1]):
            self._park(pane_id)

        placeholder = self._require_placeholder()
        if placeholder:
            _log(f"ContentZone.hide_all: swap-pane -s {placeholder} -t {keep}")
            run_command(["tmux", "swap-pane", "-s", placeholder, "-t", keep], check=False)
            self._visible = []
            self._enforce_invariant()
            _enforce_monitor_min_width(self._session)
            _log_layout(self._session)

    def remove(self, pane_id: str) -> None:
        if not pane_id:
            return
        if pane_id in self._visible:
            self.hide(pane_id)
        _log(f"ContentZone.remove: kill-pane {pane_id}")
        run_command(["tmux", "kill-pane", "-t", pane_id], check=False)
        self._visible = [current for current in self._visible if current != pane_id]
        _enforce_monitor_min_width(self._session)

    def _visible_from_snapshot(self, known_panes: list[str]) -> list[str]:
        known = {pane_id for pane_id in known_panes if pane_id}
        return [pane_id for pane_id in self._visible if pane_id in known]

    def _park(self, pane_id: str) -> None:
        _log(f"ContentZone: break-pane -d -s {pane_id} -n _hidden")
        run_command(["tmux", "break-pane", "-d", "-s", pane_id, "-n", "_hidden"], check=False)

    def _require_placeholder(self) -> str | None:
        if self._placeholder and tmux_pane_exists(self._placeholder):
            return self._placeholder
        placeholder = _get_placeholder_id(self._session)
        if placeholder and tmux_pane_exists(placeholder):
            self._placeholder = placeholder
            return placeholder
        return None

    def _ensure_placeholder_hidden(self) -> None:
        placeholder = self._require_placeholder()
        if placeholder and _pane_in_window(placeholder, MAIN_WINDOW):
            self._park(placeholder)

    def _ensure_placeholder_visible(self) -> None:
        placeholder = self._require_placeholder()
        if not placeholder:
            return
        if _pane_in_window(placeholder, MAIN_WINDOW):
            return
        for pane_id in reversed(self._visible):
            if tmux_pane_exists(pane_id) and _pane_in_window(pane_id, MAIN_WINDOW):
                _log(f"ContentZone: swap-pane -s {placeholder} -t {pane_id}")
                run_command(["tmux", "swap-pane", "-s", placeholder, "-t", pane_id], check=False)
                return
        control = _find_control_pane(self._session)
        if control:
            _log(f"ContentZone: join-pane -h -s {placeholder} -t {control}")
            run_command(["tmux", "join-pane", "-h", "-s", placeholder, "-t", control], check=False)
            _enforce_monitor_min_width(self._session)

    def _enforce_invariant(self) -> None:
        if self._visible:
            self._ensure_placeholder_hidden()
        else:
            self._ensure_placeholder_visible()

    def _rebalance_visible_panes(self) -> None:
        if len(self._visible) < 2:
            return
        for pane_id in self._visible:
            if tmux_pane_exists(pane_id) and _pane_in_window(pane_id, MAIN_WINDOW):
                _log(f"ContentZone: select-layout -E -t {pane_id}")
                run_command(
                    ["tmux", "select-layout", "-E", "-t", pane_id],
                    check=False,
                )
                return


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
) -> tuple[dict[str, str | None], ContentZone]:
    """Create the tmux session with control pane + primary agent pane."""
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
    run_command(["tmux", "set-option", "-t", session_name, "pane-border-status", "top"])
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
    run_command(
        ["tmux", "break-pane", "-d", "-s", placeholder_pane, "-n", "_hidden"],
        check=False,
    )
    _set_placeholder_id(session_name, placeholder_pane)

    _log(
        f"tmux_new_session: enforcing monitor width {MONITOR_MIN_WIDTH}-{MONITOR_MAX_WIDTH}"
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


def create_agent_pane(
    session_name: str,
    agent_name: str,
    agents: dict[str, AgentConfig],
    trust_snippet: str | None,
    *,
    display_label: str | None = None,
) -> str:
    """Create a new agent pane and leave it parked in the hidden window."""
    agent = agents[agent_name]
    agent_cmd = build_agent_command(agent)
    split_target = _find_any_hidden_pane(session_name)
    if not split_target:
        raise RuntimeError(f"No pane available to seed hidden pane creation for {session_name}")

    _log(
        f"create_agent_pane: Creating {agent_name} hidden at {split_target}"
    )
    result = run_command(
        [
            "tmux",
            "split-window",
            "-v",
            "-t",
            split_target,
            "-P",
            "-F",
            "#{pane_id}",
            agent_cmd,
        ]
    )
    pane_id = result.stdout.strip()
    set_pane_identity(pane_id, role=agent.role, display_label=display_label)
    if _pane_in_window(pane_id, MAIN_WINDOW):
        run_command(["tmux", "break-pane", "-d", "-s", pane_id, "-n", "_hidden"], check=False)

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
        ["tmux", "display-message", "-p", "-t", target_pane, "#{pane_id} #{pane_dead}"],
        check=False,
    )
    if result.returncode != 0:
        return False
    parts = result.stdout.strip().split()
    if len(parts) < 2:
        return False
    return parts[1] != "1"


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


def send_prompt(target_pane: str | None, prompt_file: Path) -> None:
    """Send a prompt reference message to an existing pane."""
    if not target_pane or not tmux_pane_exists(target_pane):
        return
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
            return
        time.sleep(0.2)
