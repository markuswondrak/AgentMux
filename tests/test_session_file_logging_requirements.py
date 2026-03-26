from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentmux.event_bus import EventBus, build_wake_listener
import agentmux.session_events as session_events


class _FakeObserver:
    last_instance: "_FakeObserver | None" = None

    def __init__(self) -> None:
        self.schedule_calls: list[tuple[object, str, bool]] = []
        self.started = False
        self.stopped = False
        self.joined = False
        _FakeObserver.last_instance = self

    def schedule(self, handler, path: str, recursive: bool = False) -> None:
        self.schedule_calls.append((handler, path, recursive))

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self) -> None:
        self.joined = True


class SessionFileLoggingRequirementsTests(unittest.TestCase):
    def test_event_bus_fan_out_wakes_and_logs_created_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            wake_event = threading.Event()
            bus = EventBus()
            logger = session_events.CreatedFilesLogListener(
                feature_dir / "created_files.log",
                now=lambda: datetime(2026, 3, 25, 18, 50, 7),
            )
            bus.register(build_wake_listener(wake_event))
            bus.register(logger.handle_event)

            session_events.publish_file_event(
                bus,
                session_events.FILE_EVENT_CREATED,
                "03_research/code-topic/request.md",
            )

            self.assertTrue(wake_event.is_set())
            self.assertEqual(
                "2026-03-25 18:50:07  03_research/code-topic/request.md\n",
                (feature_dir / "created_files.log").read_text(encoding="utf-8"),
            )

    def test_modification_and_duplicate_created_events_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            bus = EventBus()
            logger = session_events.CreatedFilesLogListener(
                feature_dir / "created_files.log",
                now=lambda: datetime(2026, 3, 25, 18, 50, 7),
            )
            bus.register(logger.handle_event)

            session_events.publish_file_event(bus, session_events.FILE_EVENT_CREATED, "context.md")
            session_events.publish_file_event(bus, session_events.FILE_EVENT_ACTIVITY, "context.md")
            session_events.publish_file_event(bus, session_events.FILE_EVENT_CREATED, "context.md")

            self.assertEqual(
                ["2026-03-25 18:50:07  context.md"],
                (feature_dir / "created_files.log").read_text(encoding="utf-8").splitlines(),
            )

    def test_moved_file_is_logged_at_destination_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            bus = EventBus()
            logger = session_events.CreatedFilesLogListener(
                feature_dir / "created_files.log",
                now=lambda: datetime(2026, 3, 25, 18, 50, 7),
            )
            bus.register(logger.handle_event)
            handler = session_events.FeatureEventHandler(feature_dir, bus)

            handler.on_any_event(
                SimpleNamespace(
                    event_type="moved",
                    is_directory=False,
                    src_path="/tmp/tmp-file.txt",
                    dest_path=str(feature_dir / "04_design" / "design.md"),
                )
            )

            self.assertEqual(
                ["2026-03-25 18:50:07  04_design/design.md"],
                (feature_dir / "created_files.log").read_text(encoding="utf-8").splitlines(),
            )

    def test_seed_existing_files_logs_in_deterministic_order_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / "b.txt").write_text("b", encoding="utf-8")
            (feature_dir / "a").mkdir()
            (feature_dir / "a" / "a.txt").write_text("a", encoding="utf-8")

            bus = EventBus()
            logger = session_events.CreatedFilesLogListener(
                feature_dir / "created_files.log",
                now=lambda: datetime(2026, 3, 25, 18, 50, 7),
            )
            bus.register(logger.handle_event)

            session_events.seed_existing_files(feature_dir, bus)
            session_events.seed_existing_files(feature_dir, bus)

            self.assertEqual(
                [
                    "2026-03-25 18:50:07  a/a.txt",
                    "2026-03-25 18:50:07  b.txt",
                ],
                (feature_dir / "created_files.log").read_text(encoding="utf-8").splitlines(),
            )

    def test_file_event_source_schedules_feature_directory_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            bus = EventBus()
            source = session_events.FileEventSource(feature_dir)

            with patch("agentmux.session_events.Observer", _FakeObserver):
                source.start(bus)

            observer = _FakeObserver.last_instance
            self.assertIsNotNone(observer)
            assert observer is not None
            self.assertTrue(observer.started)
            self.assertEqual(1, len(observer.schedule_calls))
            _, path, recursive = observer.schedule_calls[0]
            self.assertEqual(str(feature_dir), path)
            self.assertTrue(recursive)

            source.stop()
            self.assertTrue(observer.stopped)
            self.assertTrue(observer.joined)


if __name__ == "__main__":
    unittest.main()
