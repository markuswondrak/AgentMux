from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - handled at runtime
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None

FILE_EVENT_ACTIVITY = "activity"
FILE_EVENT_CREATED = "created"
CREATED_FILES_LOG_NAME = "created_files.log"


def ensure_watchdog_available() -> None:
    if Observer is None:
        raise SystemExit(
            "Missing dependency: watchdog. Install it with `python3 -m pip install -r requirements.txt`."
        )


@dataclass(frozen=True)
class SessionFileEvent:
    event_type: str
    relative_path: str


class SessionFileEventDispatcher:
    def __init__(self) -> None:
        self._listeners: list[Callable[[SessionFileEvent], None]] = []

    def register(self, listener: Callable[[SessionFileEvent], None]) -> None:
        self._listeners.append(listener)

    def publish(self, event: SessionFileEvent) -> None:
        for listener in list(self._listeners):
            listener(event)


def build_transition_wake_listener(wake_event: threading.Event) -> Callable[[SessionFileEvent], None]:
    def _listener(event: SessionFileEvent) -> None:
        _ = event
        wake_event.set()

    return _listener


class CreatedFilesLogListener:
    def __init__(
        self,
        log_path: Path,
        now: Callable[[], datetime] | None = None,
        log_relative_path: str = CREATED_FILES_LOG_NAME,
    ) -> None:
        self.log_path = log_path
        self._now = now or datetime.now
        self._log_relative_path = log_relative_path
        self._seen_relative_paths: set[str] = set()

    def handle_event(self, event: SessionFileEvent) -> None:
        if event.event_type != FILE_EVENT_CREATED:
            return
        if event.relative_path == self._log_relative_path:
            return
        if event.relative_path in self._seen_relative_paths:
            return
        self._seen_relative_paths.add(event.relative_path)
        timestamp = self._now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp}  {event.relative_path}\n")


def seed_existing_files(feature_dir: Path, dispatcher: SessionFileEventDispatcher) -> None:
    feature_root = feature_dir.resolve()
    relative_paths: list[str] = []
    for candidate in feature_dir.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            relative_path = candidate.resolve().relative_to(feature_root).as_posix()
        except ValueError:
            continue
        if relative_path == CREATED_FILES_LOG_NAME:
            continue
        relative_paths.append(relative_path)

    for relative_path in sorted(set(relative_paths)):
        dispatcher.publish(
            SessionFileEvent(
                event_type=FILE_EVENT_CREATED,
                relative_path=relative_path,
            )
        )


class FeatureEventHandler(FileSystemEventHandler):
    def __init__(self, feature_dir: Path, dispatcher: SessionFileEventDispatcher) -> None:
        super().__init__()
        self.feature_dir = feature_dir.resolve()
        self.dispatcher = dispatcher

    def _normalize_path(self, raw_path: str | None) -> str | None:
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.feature_dir / candidate
        try:
            return candidate.resolve().relative_to(self.feature_dir).as_posix()
        except ValueError:
            return None

    def on_any_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "is_directory", False):
            return

        event_type = str(getattr(event, "event_type", ""))
        src_relative = self._normalize_path(getattr(event, "src_path", None))

        if event_type == "moved":
            dest_relative = self._normalize_path(getattr(event, "dest_path", None))
            if dest_relative is not None:
                self.dispatcher.publish(
                    SessionFileEvent(
                        event_type=FILE_EVENT_CREATED,
                        relative_path=dest_relative,
                    )
                )
                self.dispatcher.publish(
                    SessionFileEvent(
                        event_type=FILE_EVENT_ACTIVITY,
                        relative_path=dest_relative,
                    )
                )
                return
            if src_relative is not None:
                self.dispatcher.publish(
                    SessionFileEvent(
                        event_type=FILE_EVENT_ACTIVITY,
                        relative_path=src_relative,
                    )
                )
            return

        if src_relative is None:
            return

        if event_type == "created":
            self.dispatcher.publish(
                SessionFileEvent(
                    event_type=FILE_EVENT_CREATED,
                    relative_path=src_relative,
                )
            )
        self.dispatcher.publish(
            SessionFileEvent(
                event_type=FILE_EVENT_ACTIVITY,
                relative_path=src_relative,
            )
        )


@dataclass
class SessionFileMonitor:
    observer: Any
    dispatcher: SessionFileEventDispatcher

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join()


def start_session_file_monitor(
    feature_dir: Path,
    created_files_log: Path,
    wake_event: threading.Event,
) -> SessionFileMonitor:
    ensure_watchdog_available()
    dispatcher = SessionFileEventDispatcher()
    dispatcher.register(build_transition_wake_listener(wake_event))
    dispatcher.register(CreatedFilesLogListener(created_files_log).handle_event)
    seed_existing_files(feature_dir, dispatcher)

    observer = Observer()
    observer.schedule(FeatureEventHandler(feature_dir, dispatcher), str(feature_dir), recursive=True)
    observer.start()
    return SessionFileMonitor(observer=observer, dispatcher=dispatcher)
