from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .event_bus import EventBus, SessionEvent

if TYPE_CHECKING:
    from . import RegisteredPaneRef, TmuxAgentRuntime


INTERRUPTION_SOURCE_NAME = "interruption"
INTERRUPTION_EVENT_PANE_EXITED = "interruption.pane_exited"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[ORCH {ts}] {msg}")


def _read_log_tail(log_path: Path, max_lines: int = 20) -> str | None:
    """Read the last N lines of a log file, returning None if unavailable."""
    try:
        if not log_path.exists():
            return None
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail).strip() or None
    except OSError:
        return None


class InterruptionEventSource:
    def __init__(
        self, runtime: TmuxAgentRuntime, *, poll_interval: float = 0.25
    ) -> None:
        self._runtime = runtime
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._reported: set[tuple[str, str, str | None]] = set()

    def start(self, bus: EventBus) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(bus,),
            daemon=True,
            name="agentmux-interruption-source",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def poll_once(self, bus: EventBus) -> None:
        missing_panes = self._runtime.unexpected_missing_registered_panes()
        if missing_panes:
            _log(f"Interruption detection: found {len(missing_panes)} missing pane(s)")
        for pane in missing_panes:
            event_key = self._event_key(pane)
            if event_key in self._reported:
                continue
            self._reported.add(event_key)
            is_expected = self._runtime.is_expected_missing_pane(pane.pane_id)

            # Try to read the tail of the output log for diagnostics
            log_path = self._runtime.get_pane_output_log(pane.pane_id)
            log_tail = _read_log_tail(log_path) if log_path else None
            if log_tail:
                _log(f"  output.log tail:\n{log_tail}")

            message = (
                f"Agent pane {pane.label} was closed or exited "
                "(for example via Ctrl-C)."
            )
            extra_info = ""
            if log_tail:
                extra_info = f"\n\nLast lines of output.log:\n{log_tail}"

            _log(
                f"Interruption: pane_exited role={pane.role} scope={pane.scope} "
                f"task_id={pane.task_id} pane_id={pane.pane_id} expected={is_expected}"
            )
            bus.publish(
                SessionEvent(
                    kind=INTERRUPTION_EVENT_PANE_EXITED,
                    source=INTERRUPTION_SOURCE_NAME,
                    payload={
                        "interruption_type": "pane_exited",
                        "role": pane.role,
                        "pane_scope": pane.scope,
                        "task_id": pane.task_id,
                        "pane_id": pane.pane_id,
                        "label": pane.label,
                        "message": message + extra_info,
                    },
                )
            )

    def _event_key(self, pane: RegisteredPaneRef) -> tuple[str, str, str | None]:
        task_id = None if pane.task_id is None else str(pane.task_id)
        return pane.scope, pane.role, task_id

    def _run(self, bus: EventBus) -> None:
        while not self._stop_event.is_set():
            self.poll_once(bus)
            self._stop_event.wait(self._poll_interval)
