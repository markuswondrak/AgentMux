from __future__ import annotations

import unittest

from agentmux.event_bus import EventBus
from agentmux.interruption_sources import INTERRUPTION_EVENT_PANE_EXITED, InterruptionEventSource
from agentmux.runtime import RegisteredPaneRef


class _FakeRuntime:
    def __init__(self, missing: list[RegisteredPaneRef]) -> None:
        self._missing = list(missing)

    def missing_registered_panes(self) -> list[RegisteredPaneRef]:
        return list(self._missing)


class InterruptionEventSourceTests(unittest.TestCase):
    def test_poll_once_emits_event_for_missing_primary_pane(self) -> None:
        source = InterruptionEventSource(
            _FakeRuntime(
                [
                    RegisteredPaneRef(
                        role="architect",
                        pane_id="%1",
                        scope="primary",
                        label="architect",
                    )
                ]
            )
        )
        bus = EventBus()
        seen = []
        bus.register(seen.append)

        source.poll_once(bus)

        self.assertEqual(1, len(seen))
        self.assertEqual(INTERRUPTION_EVENT_PANE_EXITED, seen[0].kind)
        self.assertEqual("architect", seen[0].payload["role"])
        self.assertEqual("primary", seen[0].payload["pane_scope"])
        self.assertEqual("%1", seen[0].payload["pane_id"])

    def test_poll_once_emits_event_for_missing_parallel_pane_once(self) -> None:
        source = InterruptionEventSource(
            _FakeRuntime(
                [
                    RegisteredPaneRef(
                        role="coder",
                        pane_id="%9",
                        scope="parallel",
                        task_id=2,
                        label="coder 2",
                    )
                ]
            )
        )
        bus = EventBus()
        seen = []
        bus.register(seen.append)

        source.poll_once(bus)
        source.poll_once(bus)

        self.assertEqual(1, len(seen))
        self.assertEqual(2, seen[0].payload["task_id"])
        self.assertEqual("coder 2", seen[0].payload["label"])


if __name__ == "__main__":
    unittest.main()
