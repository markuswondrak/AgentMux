from __future__ import annotations

from ..terminal_ui.layout import MONITOR_MAX_WIDTH, MONITOR_MIN_WIDTH
from .tmux_core import MAIN_WINDOW, _log, run_command, tmux_pane_exists

# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------


def _log_layout(session_name: str) -> None:
    """Log current window layout and main-pane-width."""
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


def _park_to_hidden(pane_id: str) -> None:
    """Move a pane to the _hidden window (break-pane -d)."""
    run_command(
        ["tmux", "break-pane", "-d", "-s", pane_id, "-n", "_hidden"], check=False
    )


def set_pane_identity(
    pane_id: str,
    *,
    role: str,
    display_label: str | None = None,
) -> None:
    visible_label = (display_label or role).strip()
    run_command(
        ["tmux", "select-pane", "-t", pane_id, "-T", visible_label], check=False
    )
    run_command(["tmux", "set-option", "-p", "-t", pane_id, "@role", role], check=False)
    run_command(
        [
            "tmux",
            "set-option",
            "-p",
            "-t",
            pane_id,
            "@pane_label",
            (display_label or "").strip(),
        ],
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
            _log(f"ContentZone.show: swap {pane_id} <-> {placeholder}")
            self._swap_panes(pane_id, placeholder)
        else:
            keep = pane_id if pane_id in self._visible else self._visible[-1]
            for other in list(self._visible):
                if other != keep:
                    self._park(other)
            if keep != pane_id:
                _log(f"ContentZone.show: swap {pane_id} <-> {keep}")
                self._swap_panes(pane_id, keep)

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
            _log(f"ContentZone.hide: swap {placeholder} <-> {pane_id}")
            self._swap_panes(placeholder, pane_id)
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
            _log(f"ContentZone.hide_all: swap {placeholder} <-> {keep}")
            self._swap_panes(placeholder, keep)
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
        _log(f"ContentZone: parking {pane_id} to _hidden")
        _park_to_hidden(pane_id)

    def _swap_panes(self, src: str, target: str) -> None:
        run_command(["tmux", "swap-pane", "-s", src, "-t", target], check=False)

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
                _log(f"ContentZone: swap {placeholder} <-> {pane_id}")
                self._swap_panes(placeholder, pane_id)
                return
        control = _find_control_pane(self._session)
        if control:
            _log(f"ContentZone: join-pane -h -s {placeholder} -t {control}")
            run_command(
                ["tmux", "join-pane", "-h", "-s", placeholder, "-t", control],
                check=False,
            )
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
