"""Tool-call event logging and event source for the session event bus.

This module provides:
- ``append_tool_event()`` — append a structured JSON line to
  ``tool_events.jsonl`` so that downstream consumers (MCP submit tools,
  the orchestrator) can observe tool invocations.
- ``ToolCallEventSource`` — an ``EventSource`` that seeds existing entries
  from ``tool_events.jsonl`` and tails the file via watchdog, publishing
  ``SessionEvent(kind="tool.<name>", source="tool_call", ...)`` to the bus.
- Cursor helpers for persisting the last applied tool-event offset so resume
  can continue from the exact next unapplied signal.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .event_bus import EventBus, EventSource, SessionEvent

logger = logging.getLogger(__name__)

TOOL_EVENTS_LOG_NAME = "tool_events.jsonl"
TOOL_EVENT_CURSOR_STATE_NAME = "tool_event_state.json"
TOOL_EVENT_CURSOR_STATE_VERSION = 1
TOOL_EVENT_META_KEY = "_tool_event_meta"


def _tool_event_cursor_path(feature_dir: Path) -> Path:
    return feature_dir / TOOL_EVENT_CURSOR_STATE_NAME


def load_tool_event_cursor(feature_dir: Path) -> int:
    """Load the persisted applied-cursor for ``tool_events.jsonl``."""
    cursor_path = _tool_event_cursor_path(feature_dir)
    if not cursor_path.exists():
        return 0
    try:
        raw = json.loads(cursor_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(raw, dict):
        return 0
    cursor = raw.get("applied_cursor", 0)
    try:
        return max(int(cursor), 0)
    except (TypeError, ValueError):
        return 0


def persist_tool_event_cursor(feature_dir: Path, cursor: int) -> None:
    """Persist the applied-cursor for ``tool_events.jsonl`` atomically."""
    normalized_cursor = max(int(cursor), 0)
    cursor_path = _tool_event_cursor_path(feature_dir)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": TOOL_EVENT_CURSOR_STATE_VERSION,
        "applied_cursor": normalized_cursor,
    }
    tmp_path = cursor_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp_path.rename(cursor_path)


def tool_event_cursor_from_session_event(event: SessionEvent) -> int | None:
    """Extract the applied-cursor offset from a tool-call ``SessionEvent``."""
    meta = event.payload.get(TOOL_EVENT_META_KEY)
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("end_offset")
    try:
        normalized = int(cursor)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def append_tool_event(
    log_path: Path,
    tool_name: str,
    payload: dict[str, Any],
) -> None:
    """Append one JSON line to *log_path* describing a tool call.

    Creates parent directories if they do not exist.  Subsequent calls
    append without truncating.
    """
    entry = {
        "tool": tool_name,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "payload": payload,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class ToolCallEventSource(EventSource):
    """Watch ``tool_events.jsonl`` and emit ``SessionEvent`` objects.

    On ``start()`` the source seeds any pre-existing lines, then tails
    the file for new appends via a watchdog observer.
    """

    def __init__(self, feature_dir: Path) -> None:
        self._feature_dir = feature_dir.resolve()
        self._offset = 0
        self._observer: Any = None
        self._read_lock = threading.Lock()

    def start(self, bus: EventBus) -> None:
        from .file_events import ensure_watchdog_available

        ensure_watchdog_available()

        self._offset = load_tool_event_cursor(self._feature_dir)
        self._seed_existing(bus)

        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer

        class _ToolLogHandler(FileSystemEventHandler):
            def __init__(self, source: ToolCallEventSource, bus: EventBus) -> None:
                super().__init__()
                self._source = source
                self._bus = bus

            def on_any_event(self, event: FileSystemEvent) -> None:
                if getattr(event, "is_directory", False):
                    return
                src = getattr(event, "src_path", "")
                if Path(src).name != TOOL_EVENTS_LOG_NAME:
                    return
                self._source._on_modified(self._bus)

        observer = Observer()
        observer.schedule(
            _ToolLogHandler(self, bus),
            str(self._feature_dir),
            recursive=False,
        )
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None

    def _read_and_emit_from_offset(self, bus: EventBus) -> None:
        """Read and emit all lines from ``self._offset`` to EOF, then update offset.

        Opens the tool-events log, seeks to the current cursor, and emits a
        ``SessionEvent`` for every non-empty line.  Updates ``self._offset``
        to the new file position so subsequent calls resume where this one
        left off.
        """
        log_path = self._feature_dir / TOOL_EVENTS_LOG_NAME
        if not log_path.exists():
            return

        with log_path.open("r", encoding="utf-8") as f:
            f.seek(self._offset)
            while True:
                start_offset = f.tell()
                line = f.readline()
                if not line:
                    break
                end_offset = f.tell()
                stripped = line.rstrip("\n")
                if stripped:
                    self._emit_line(
                        stripped,
                        bus,
                        start_offset=start_offset,
                        end_offset=end_offset,
                    )
            self._offset = f.tell()

    def _seed_existing(self, bus: EventBus) -> None:
        """Replay pre-existing log entries from before ``start()`` was called."""
        with self._read_lock:
            current_size = self._current_log_size()
            if self._offset > current_size:
                logger.warning(
                    "tool event cursor %s exceeds log size %s; replaying from start",
                    self._offset,
                    current_size,
                )
                self._offset = 0
                persist_tool_event_cursor(self._feature_dir, 0)
            self._read_and_emit_from_offset(bus)

    def _on_modified(self, bus: EventBus) -> None:
        """Handle a watchdog modification event — emit only newly appended lines."""
        with self._read_lock:
            current_size = self._current_log_size()
            if current_size <= self._offset:
                return
            self._read_and_emit_from_offset(bus)

    def _current_log_size(self) -> int:
        """Return the current byte size of the tool-events log, or 0 if absent."""
        log_path = self._feature_dir / TOOL_EVENTS_LOG_NAME
        if not log_path.exists():
            return 0
        return log_path.stat().st_size

    def _emit_line(
        self,
        line: str,
        bus: EventBus,
        *,
        start_offset: int,
        end_offset: int,
    ) -> None:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Skipping malformed tool event line: %s", line[:120])
            return
        if not isinstance(entry, dict):
            logger.warning("Skipping non-object tool event line: %s", line[:120])
            return

        tool_name = entry.get("tool", "unknown")
        payload = dict(entry)
        payload[TOOL_EVENT_META_KEY] = {
            "start_offset": start_offset,
            "end_offset": end_offset,
        }
        bus.publish(
            SessionEvent(
                kind=f"tool.{tool_name}",
                source="tool_call",
                payload=payload,
            )
        )
