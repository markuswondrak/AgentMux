from __future__ import annotations

import threading
import unittest

from agentmux.event_bus import EventBus, SessionEvent, build_wake_listener


class _FakeSource:
    def __init__(self) -> None:
        self.started_with = None
        self.stop_calls = 0

    def start(self, bus: EventBus) -> None:
        self.started_with = bus

    def stop(self) -> None:
        self.stop_calls += 1


class EventBusTests(unittest.TestCase):
    def test_event_bus_fans_out_to_multiple_listeners(self) -> None:
        bus = EventBus()
        seen: list[tuple[str, str]] = []

        bus.register(lambda event: seen.append(("a", event.kind)))
        bus.register(lambda event: seen.append(("b", event.kind)))

        bus.publish(SessionEvent(kind="file.created", source="file"))

        self.assertEqual([("a", "file.created"), ("b", "file.created")], seen)

    def test_event_bus_starts_and_stops_sources(self) -> None:
        source_a = _FakeSource()
        source_b = _FakeSource()
        bus = EventBus(sources=[source_a, source_b])

        bus.start()
        bus.stop()

        self.assertIs(source_a.started_with, bus)
        self.assertIs(source_b.started_with, bus)
        self.assertEqual(1, source_a.stop_calls)
        self.assertEqual(1, source_b.stop_calls)

    def test_build_wake_listener_sets_event(self) -> None:
        wake_event = threading.Event()
        listener = build_wake_listener(wake_event)

        listener(SessionEvent(kind="interruption.pane_exited", source="interruption"))

        self.assertTrue(wake_event.is_set())


if __name__ == "__main__":
    unittest.main()
