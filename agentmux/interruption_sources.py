from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .event_bus import EventBus, SessionEvent

if TYPE_CHECKING:
    from .runtime import RegisteredPaneRef, TmuxAgentRuntime


INTERRUPTION_SOURCE_NAME = "interruption"
INTERRUPTION_EVENT_PANE_EXITED = "interruption.pane_exited"


class InterruptionEventSource:
    def __init__(self, runtime: "TmuxAgentRuntime", *, poll_interval: float = 0.25) -> None:
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
        for pane in self._runtime.missing_registered_panes():
            event_key = self._event_key(pane)
            if event_key in self._reported:
                continue
            self._reported.add(event_key)
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
                        "message": f"Agent pane {pane.label} was closed or exited (for example via Ctrl-C).",
                    },
                )
            )

    def _event_key(self, pane: "RegisteredPaneRef") -> tuple[str, str, str | None]:
        task_id = None if pane.task_id is None else str(pane.task_id)
        return pane.scope, pane.role, task_id

    def _run(self, bus: EventBus) -> None:
        while not self._stop_event.is_set():
            self.poll_once(bus)
            self._stop_event.wait(self._poll_interval)
