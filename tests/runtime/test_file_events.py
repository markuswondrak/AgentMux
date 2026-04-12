from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from watchdog.events import FileModifiedEvent, FileMovedEvent

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

from agentmux.runtime.event_bus import EventBus, SessionEvent
from agentmux.runtime.file_events import (
    RUNTIME_FILE_NAMES,
    FeatureEventHandler,
    seed_existing_files,
)


@unittest.skipUnless(WATCHDOG_AVAILABLE, "watchdog not installed")
class RuntimeFileExclusionTests(unittest.TestCase):
    """Tests that runtime files are excluded from event publishing."""

    def test_runtime_file_names_constant(self) -> None:
        """Verify RUNTIME_FILE_NAMES contains expected runtime files."""
        expected_files = {
            "orchestrator.log",
            "state.json",
            "runtime_state.json",
            "created_files.log",
            "status_log.txt",
            "tool_events.jsonl",
            "tool_event_state.json",
        }
        self.assertEqual(RUNTIME_FILE_NAMES, expected_files)

    def test_feature_event_handler_excludes_runtime_files(self) -> None:
        """Verify FeatureEventHandler does not publish events for runtime files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            bus = EventBus()
            received_events: list[SessionEvent] = []
            bus.register(lambda event: received_events.append(event))

            handler = FeatureEventHandler(feature_dir, bus)

            # Test that runtime files are excluded
            for filename in RUNTIME_FILE_NAMES:
                event = FileModifiedEvent(src_path=str(feature_dir / filename))
                handler.on_any_event(event)

            self.assertEqual(
                len(received_events), 0, "Runtime files should not trigger events"
            )

    def test_feature_event_handler_allows_non_runtime_files(self) -> None:
        """Verify FeatureEventHandler publishes events for non-runtime files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            bus = EventBus()
            received_events: list[SessionEvent] = []
            bus.register(lambda event: received_events.append(event))

            handler = FeatureEventHandler(feature_dir, bus)

            # Create a test file
            test_file = feature_dir / "plan.md"
            test_file.write_text("test content")

            # Test that non-runtime files trigger events
            event = FileModifiedEvent(src_path=str(test_file))
            handler.on_any_event(event)

            self.assertEqual(len(received_events), 1)
            self.assertEqual(received_events[0].kind, "file.activity")
            self.assertEqual(received_events[0].payload["relative_path"], "plan.md")

    def test_feature_event_handler_excludes_runtime_files_in_subdirs(self) -> None:
        """Verify runtime files in subdirectories are also excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            bus = EventBus()
            received_events: list[SessionEvent] = []
            bus.register(lambda event: received_events.append(event))

            handler = FeatureEventHandler(feature_dir, bus)

            # Test runtime file in subdirectory
            subdir = feature_dir / "subdir"
            subdir.mkdir()
            event = FileModifiedEvent(src_path=str(subdir / "orchestrator.log"))
            handler.on_any_event(event)

            self.assertEqual(
                len(received_events),
                0,
                "Runtime files in subdirs should not trigger events",
            )

    def test_feature_event_handler_excludes_runtime_files_in_moved_events(self) -> None:
        """Verify runtime files are excluded from moved events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            bus = EventBus()
            received_events: list[SessionEvent] = []
            bus.register(lambda event: received_events.append(event))

            handler = FeatureEventHandler(feature_dir, bus)

            # Test that moved runtime files are excluded
            event = FileMovedEvent(
                src_path=str(feature_dir / "old.log"),
                dest_path=str(feature_dir / "orchestrator.log"),
            )
            handler.on_any_event(event)

            self.assertEqual(
                len(received_events), 0, "Moved runtime files should not trigger events"
            )

    def test_seed_existing_files_excludes_runtime_files(self) -> None:
        """Verify seed_existing_files does not publish events for runtime files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            bus = EventBus()
            received_events: list[SessionEvent] = []
            bus.register(lambda event: received_events.append(event))

            # Create runtime files
            for filename in RUNTIME_FILE_NAMES:
                (feature_dir / filename).write_text("test")

            # Create a non-runtime file
            (feature_dir / "plan.md").write_text("test plan")

            seed_existing_files(feature_dir, bus)

            # Should only have one event for plan.md
            self.assertEqual(len(received_events), 1)
            self.assertEqual(received_events[0].payload["relative_path"], "plan.md")


if __name__ == "__main__":
    unittest.main()
