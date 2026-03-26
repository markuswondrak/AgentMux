from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Protocol


@dataclass(frozen=True)
class SessionEvent:
    kind: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )


EventListener = Callable[[SessionEvent], None]


class EventSource(Protocol):
    def start(self, bus: "EventBus") -> None:
        ...

    def stop(self) -> None:
        ...


class EventBus:
    def __init__(self, *, sources: Iterable[EventSource] | None = None) -> None:
        self._listeners: list[EventListener] = []
        self._sources = list(sources or [])
        self._lock = threading.Lock()

    def register(self, listener: EventListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def publish(self, event: SessionEvent) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener(event)

    def start(self) -> None:
        for source in self._sources:
            source.start(self)

    def stop(self) -> None:
        for source in reversed(self._sources):
            source.stop()


def build_wake_listener(wake_event: threading.Event) -> EventListener:
    def _listener(event: SessionEvent) -> None:
        _ = event
        wake_event.set()

    return _listener
