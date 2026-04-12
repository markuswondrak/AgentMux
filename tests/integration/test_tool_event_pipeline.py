"""Integration smoke test: tool_events.jsonl → EventBus pipeline.

Tests that ToolCallEventSource correctly reads tool_events.jsonl and
publishes SessionEvent objects to the EventBus without requiring tmux
or real agents.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.runtime.event_bus import EventBus, SessionEvent
from agentmux.runtime.tool_events import (
    TOOL_EVENT_META_KEY,
    ToolCallEventSource,
    append_tool_event,
)


class FakeEventBus:
    """Minimal EventBus stand-in that captures published events."""

    def __init__(self) -> None:
        self.events: list[SessionEvent] = []

    def publish(self, event: SessionEvent) -> None:
        self.events.append(event)


class TestToolEventPipeline(unittest.TestCase):
    """Smoke tests for the tool_events.jsonl → EventBus pipeline."""

    def test_append_tool_event_writes_jsonl(self) -> None:
        """append_tool_event writes a valid JSONL line to the log file."""
        import json

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "tool_events.jsonl"
            append_tool_event(log_path, "submit_done", {"subplan_index": 1})

            self.assertTrue(log_path.exists())
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, len(lines))
            entry = json.loads(lines[0])
            self.assertEqual("submit_done", entry["tool"])
            self.assertEqual({"subplan_index": 1}, entry["payload"])
            self.assertIn("timestamp", entry)

    def test_append_tool_event_appends_multiple_lines(self) -> None:
        """Multiple append_tool_event calls produce multiple lines."""
        import json

        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "tool_events.jsonl"
            append_tool_event(log_path, "submit_done", {"subplan_index": 1})
            append_tool_event(log_path, "submit_review", {"verdict": "pass"})

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            self.assertEqual("submit_done", json.loads(lines[0])["tool"])
            self.assertEqual("submit_review", json.loads(lines[1])["tool"])

    def test_seed_existing_emits_event_for_each_line(self) -> None:
        """_seed_existing publishes a SessionEvent per JSONL line."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "tool_events.jsonl"
            append_tool_event(log_path, "submit_done", {"subplan_index": 1})

            source = ToolCallEventSource(feature_dir=feature_dir)
            bus = FakeEventBus()
            source._seed_existing(bus)

            self.assertEqual(1, len(bus.events))
            event = bus.events[0]
            self.assertEqual("tool.submit_done", event.kind)
            self.assertEqual("submit_done", event.payload.get("tool"))
            self.assertEqual({"subplan_index": 1}, event.payload.get("payload"))
            self.assertEqual("tool_call", event.source)

    def test_seed_existing_emits_events_for_multiple_lines(self) -> None:
        """_seed_existing emits one event per JSONL line."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "tool_events.jsonl"
            append_tool_event(log_path, "submit_done", {"subplan_index": 1})
            append_tool_event(log_path, "submit_review", {"verdict": "pass"})

            source = ToolCallEventSource(feature_dir=feature_dir)
            bus = FakeEventBus()
            source._seed_existing(bus)

            self.assertEqual(2, len(bus.events))
            self.assertEqual("tool.submit_done", bus.events[0].kind)
            self.assertEqual("tool.submit_review", bus.events[1].kind)

    def test_seed_existing_noop_when_file_missing(self) -> None:
        """_seed_existing does nothing when tool_events.jsonl is absent."""
        with tempfile.TemporaryDirectory() as td:
            source = ToolCallEventSource(feature_dir=Path(td))
            bus = FakeEventBus()
            source._seed_existing(bus)

            self.assertEqual(0, len(bus.events))

    def test_seed_existing_skips_malformed_lines(self) -> None:
        """_seed_existing skips non-JSON lines without crashing."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "tool_events.jsonl"
            log_path.write_text("not-json\n", encoding="utf-8")

            source = ToolCallEventSource(feature_dir=feature_dir)
            bus = FakeEventBus()
            source._seed_existing(bus)

            self.assertEqual(0, len(bus.events))

    def test_on_modified_emits_only_new_lines(self) -> None:
        """_on_modified emits only lines added after the initial seed."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "tool_events.jsonl"
            append_tool_event(log_path, "submit_done", {"subplan_index": 1})

            source = ToolCallEventSource(feature_dir=feature_dir)
            bus = FakeEventBus()
            # Seed to advance the offset past the first line
            source._seed_existing(bus)
            self.assertEqual(1, len(bus.events))

            # Append a new event after the seed
            append_tool_event(log_path, "submit_review", {"verdict": "pass"})
            source._on_modified(bus)

            # Should only see the new event (total = 2, but _on_modified adds 1)
            self.assertEqual(2, len(bus.events))
            self.assertEqual("tool.submit_review", bus.events[1].kind)

    def test_emit_line_produces_correct_session_event(self) -> None:
        """_emit_line builds a SessionEvent with kind=tool.<name>."""
        import json

        with tempfile.TemporaryDirectory() as td:
            source = ToolCallEventSource(feature_dir=Path(td))
            bus = FakeEventBus()
            entry = {
                "tool": "submit_done",
                "timestamp": "2026-04-08T12:00:00+00:00",
                "payload": {"subplan_index": 3},
            }
            source._emit_line(json.dumps(entry), bus, start_offset=0, end_offset=42)

            self.assertEqual(1, len(bus.events))
            event = bus.events[0]
            self.assertIsInstance(event, SessionEvent)
            self.assertEqual("tool.submit_done", event.kind)
            self.assertEqual("tool_call", event.source)
            self.assertEqual("submit_done", event.payload.get("tool"))
            self.assertEqual({"subplan_index": 3}, event.payload.get("payload"))
            self.assertEqual(
                {"start_offset": 0, "end_offset": 42},
                event.payload.get(TOOL_EVENT_META_KEY),
            )

    def test_tool_call_event_source_integrates_with_real_event_bus(self) -> None:
        """ToolCallEventSource publishes to a real EventBus via _seed_existing."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "tool_events.jsonl"
            append_tool_event(
                log_path,
                "submit_done",
                {"subplan_index": 1},
            )

            received: list[SessionEvent] = []
            bus = EventBus()
            bus.register(received.append)

            source = ToolCallEventSource(feature_dir=feature_dir)
            # Directly seed (bypasses watchdog — no filesystem watching needed)
            source._seed_existing(bus)

            self.assertEqual(1, len(received))
            event = received[0]
            self.assertEqual("tool.submit_done", event.kind)
            self.assertEqual("submit_done", event.payload.get("tool"))
            self.assertEqual({"subplan_index": 1}, event.payload.get("payload"))


if __name__ == "__main__":
    unittest.main()
