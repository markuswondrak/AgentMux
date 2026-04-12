from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - handled at runtime
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None

from .event_bus import EventBus, SessionEvent

FILE_EVENT_ACTIVITY = "activity"
FILE_EVENT_CREATED = "created"
FILE_EVENT_KIND_ACTIVITY = "file.activity"
FILE_EVENT_KIND_CREATED = "file.created"
FILE_EVENT_SOURCE = "file"
CREATED_FILES_LOG_NAME = "created_files.log"

# Runtime files written by the orchestrator that should not trigger events
# to prevent feedback loops
RUNTIME_FILE_NAMES = {
    "orchestrator.log",
    "state.json",
    "runtime_state.json",
    "created_files.log",
    "status_log.txt",
    "tool_events.jsonl",
    "tool_event_state.json",
}


def ensure_watchdog_available() -> None:
    if Observer is None:
        raise SystemExit(
            "Missing dependency: watchdog. "
            "Install it with `python3 -m pip install -r requirements.txt`."
        )


def _event_kind_for_type(event_type: str) -> str:
    if event_type == FILE_EVENT_CREATED:
        return FILE_EVENT_KIND_CREATED
    return FILE_EVENT_KIND_ACTIVITY


def publish_file_event(bus: EventBus, event_type: str, relative_path: str) -> None:
    bus.publish(
        SessionEvent(
            kind=_event_kind_for_type(event_type),
            source=FILE_EVENT_SOURCE,
            payload={
                "event_type": event_type,
                "relative_path": relative_path,
            },
        )
    )


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

    def handle_event(self, event: SessionEvent) -> None:
        if event.kind != FILE_EVENT_KIND_CREATED:
            return
        relative_path = str(event.payload.get("relative_path", "")).strip()
        if not relative_path or relative_path == self._log_relative_path:
            return
        if relative_path in self._seen_relative_paths:
            return
        self._seen_relative_paths.add(relative_path)
        timestamp = self._now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp}  {relative_path}\n")


def seed_existing_files(feature_dir: Path, bus: EventBus) -> None:
    feature_root = feature_dir.resolve()
    relative_paths: list[str] = []
    for candidate in feature_dir.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            relative_path = candidate.resolve().relative_to(feature_root).as_posix()
        except ValueError:
            continue
        # Skip runtime files
        if Path(relative_path).name in RUNTIME_FILE_NAMES:
            continue
        relative_paths.append(relative_path)

    for relative_path in sorted(set(relative_paths)):
        publish_file_event(bus, FILE_EVENT_CREATED, relative_path)


class FeatureEventHandler(FileSystemEventHandler):
    def __init__(self, feature_dir: Path, bus: EventBus) -> None:
        super().__init__()
        self.feature_dir = feature_dir.resolve()
        self._bus = bus

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

        # Exclude runtime files written by the orchestrator to prevent feedback loop
        if src_relative is not None:
            filename = Path(src_relative).name
            if filename in RUNTIME_FILE_NAMES:
                return

        if event_type == "moved":
            dest_relative = self._normalize_path(getattr(event, "dest_path", None))
            if dest_relative is not None:
                # Also check dest for runtime files
                if Path(dest_relative).name in RUNTIME_FILE_NAMES:
                    return
                publish_file_event(self._bus, FILE_EVENT_CREATED, dest_relative)
                publish_file_event(self._bus, FILE_EVENT_ACTIVITY, dest_relative)
                return
            if src_relative is not None:
                publish_file_event(self._bus, FILE_EVENT_ACTIVITY, src_relative)
            return

        if src_relative is None:
            return

        if event_type == "created":
            publish_file_event(self._bus, FILE_EVENT_CREATED, src_relative)
        publish_file_event(self._bus, FILE_EVENT_ACTIVITY, src_relative)


class FileEventSource:
    def __init__(self, feature_dir: Path) -> None:
        self._feature_dir = feature_dir
        self._observer: Any = None

    def start(self, bus: EventBus) -> None:
        ensure_watchdog_available()
        seed_existing_files(self._feature_dir, bus)
        observer = Observer()
        observer.schedule(
            FeatureEventHandler(self._feature_dir, bus),
            str(self._feature_dir),
            recursive=True,
        )
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None
