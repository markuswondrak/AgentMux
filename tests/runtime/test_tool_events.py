"""Tests for runtime/tool_events.py — ToolCallEventSource and cursor helpers."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from agentmux.runtime.event_bus import EventBus, SessionEvent
from agentmux.runtime.tool_events import (
    TOOL_EVENT_CURSOR_STATE_NAME,
    TOOL_EVENT_META_KEY,
    ToolCallEventSource,
    append_tool_event,
    load_tool_event_cursor,
    persist_tool_event_cursor,
    tool_event_cursor_from_session_event,
)


class TestAppendToolEvent(unittest.TestCase):
    """Tests for the append_tool_event helper."""

    def test_creates_log_on_first_write(self) -> None:
        """append_tool_event creates the log file on first call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "subdir" / "tool_events.jsonl"
            self.assertFalse(log_path.exists())

            append_tool_event(log_path, "test_tool", {"key": "value"})

            self.assertTrue(log_path.exists())

    def test_writes_valid_json_line(self) -> None:
        """Each line written is valid JSON with tool, timestamp, payload keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "tool_events.jsonl"

            append_tool_event(log_path, "my_tool", {"foo": "bar"})

            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["tool"], "my_tool")
            self.assertIn("timestamp", entry)
            self.assertEqual(entry["payload"], {"foo": "bar"})

    def test_appends_on_subsequent_calls(self) -> None:
        """Subsequent calls append without truncating."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "tool_events.jsonl"

            append_tool_event(log_path, "tool_a", {"a": 1})
            append_tool_event(log_path, "tool_b", {"b": 2})
            append_tool_event(log_path, "tool_c", {"c": 3})

            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 3)

            entries = [json.loads(line) for line in lines]
            self.assertEqual(entries[0]["tool"], "tool_a")
            self.assertEqual(entries[1]["tool"], "tool_b")
            self.assertEqual(entries[2]["tool"], "tool_c")


class TestToolEventCursorState(unittest.TestCase):
    """Tests for persisted tool-event cursor state."""

    def test_persist_and_load_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            persist_tool_event_cursor(feature_dir, 42)

            self.assertEqual(42, load_tool_event_cursor(feature_dir))
            self.assertTrue((feature_dir / TOOL_EVENT_CURSOR_STATE_NAME).exists())

    def test_load_cursor_defaults_to_zero_for_missing_or_invalid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            self.assertEqual(0, load_tool_event_cursor(feature_dir))

            (feature_dir / TOOL_EVENT_CURSOR_STATE_NAME).write_text(
                "not json", encoding="utf-8"
            )
            self.assertEqual(0, load_tool_event_cursor(feature_dir))


class TestToolCallEventSourceSeeding(unittest.TestCase):
    """Tests for ToolCallEventSource.start() seeding of existing entries."""

    def test_seeds_existing_entries(self) -> None:
        """start() reads all existing lines and emits SessionEvents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"

            # Pre-populate the log
            entries = [
                {
                    "tool": "submit_architecture",
                    "timestamp": "2024-01-01T00:00:00",
                    "payload": {"status": "ok"},
                },
                {
                    "tool": "submit_plan",
                    "timestamp": "2024-01-01T00:01:00",
                    "payload": {"status": "ok"},
                },
            ]
            log_path.write_text(
                "\n".join(json.dumps(e) for e in entries) + "\n",
                encoding="utf-8",
            )

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()

            self.assertEqual(len(received), 2)
            self.assertEqual(received[0].kind, "tool.submit_architecture")
            self.assertEqual(received[0].source, "tool_call")
            self.assertEqual(received[0].payload.get("payload"), {"status": "ok"})
            self.assertEqual(received[0].payload.get("tool"), "submit_architecture")
            self.assertIn(TOOL_EVENT_META_KEY, received[0].payload)
            self.assertEqual(received[1].kind, "tool.submit_plan")

    def test_seeds_empty_log(self) -> None:
        """start() with an empty log emits no events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"
            log_path.touch()

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()

            self.assertEqual(len(received), 0)

    def test_seeds_only_unapplied_lines_after_cursor(self) -> None:
        """start() resumes from the persisted applied cursor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"
            append_tool_event(log_path, "first_tool", {"seq": 1})
            append_tool_event(log_path, "second_tool", {"seq": 2})

            with log_path.open("r", encoding="utf-8") as handle:
                handle.readline()
                cursor = handle.tell()
            persist_tool_event_cursor(feature_dir, cursor)

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(received.append)

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()

            self.assertEqual(1, len(received))
            self.assertEqual("tool.second_tool", received[0].kind)
            self.assertEqual({"seq": 2}, received[0].payload.get("payload"))

    def test_seeds_no_log_file(self) -> None:
        """start() with no log file emits no events and does not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()

            self.assertEqual(len(received), 0)


try:
    import watchdog.observers  # noqa: F401

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


class TestToolCallEventSourceTailing(unittest.TestCase):
    """Tests for ToolCallEventSource tailing of new lines after start()."""

    @unittest.skipUnless(WATCHDOG_AVAILABLE, "watchdog not installed")
    def test_tails_new_lines_after_start(self) -> None:
        """Lines appended after start() produce new SessionEvent emissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)

            # Append a new line
            append_tool_event(log_path, "new_tool", {"data": "test"})

            # Give watchdog time to pick up the change
            time.sleep(0.5)

            source.stop()

            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].kind, "tool.new_tool")
            self.assertEqual(received[0].payload.get("payload"), {"data": "test"})
            self.assertEqual(received[0].payload.get("tool"), "new_tool")
            self.assertIsNotNone(tool_event_cursor_from_session_event(received[0]))

    @unittest.skipUnless(WATCHDOG_AVAILABLE, "watchdog not installed")
    def test_tails_multiple_new_lines(self) -> None:
        """Multiple lines appended after start() each produce an event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)

            append_tool_event(log_path, "tool_x", {"x": 1})
            time.sleep(0.3)
            append_tool_event(log_path, "tool_y", {"y": 2})
            time.sleep(0.3)

            source.stop()

            self.assertEqual(len(received), 2)
            kinds = {e.kind for e in received}
            self.assertIn("tool.tool_x", kinds)
            self.assertIn("tool.tool_y", kinds)


class TestToolCallEventSourceStop(unittest.TestCase):
    """Tests for ToolCallEventSource.stop() behavior."""

    def test_stop_without_start(self) -> None:
        """stop() before start() is a safe no-op."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            source = ToolCallEventSource(feature_dir)
            source.stop()  # Should not raise

    def test_double_stop(self) -> None:
        """Second stop() call is safe (no-op)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            bus = EventBus()

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()
            source.stop()  # Should not raise


class TestToolCallEventSourceMalformedLines(unittest.TestCase):
    """Tests for malformed JSON line handling."""

    def test_malformed_lines_skipped_with_warning(self) -> None:
        """Malformed JSON lines are skipped; valid lines before/after are emitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"

            valid1 = {
                "tool": "good_tool",
                "timestamp": "2024-01-01T00:00:00",
                "payload": {},
            }
            valid2 = {
                "tool": "another_good",
                "timestamp": "2024-01-01T00:01:00",
                "payload": {},
            }

            content = (
                json.dumps(valid1)
                + "\n"
                + "this is not json\n"
                + json.dumps(valid2)
                + "\n"
            )
            log_path.write_text(content, encoding="utf-8")

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()

            # Both valid lines should be emitted, malformed one skipped
            self.assertEqual(len(received), 2)
            self.assertEqual(received[0].kind, "tool.good_tool")
            self.assertEqual(received[1].kind, "tool.another_good")

    def test_all_malformed_lines(self) -> None:
        """If all lines are malformed, no events are emitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_dir = Path(tmpdir)
            log_path = feature_dir / "tool_events.jsonl"
            log_path.write_text("garbage\nmore garbage\n", encoding="utf-8")

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(lambda event: received.append(event))

            source = ToolCallEventSource(feature_dir)
            source.start(bus)
            source.stop()

            self.assertEqual(len(received), 0)


if __name__ == "__main__":
    unittest.main()
