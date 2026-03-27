from __future__ import annotations

import unittest

from agentmux.runtime.event_bus import EventBus
from agentmux.runtime.interruption_sources import INTERRUPTION_EVENT_PANE_EXITED, InterruptionEventSource
from agentmux.runtime import RegisteredPaneRef


class _FakeRuntime:
    def __init__(self, missing: list[RegisteredPaneRef], *, expected: set[str] | None = None) -> None:
        self._missing = list(missing)
        self._expected = set(expected or set())

    def missing_registered_panes(self) -> list[RegisteredPaneRef]:
        return list(self._missing)

    def is_expected_missing_pane(self, pane_id: str | None) -> bool:
        return bool(pane_id) and pane_id in self._expected


class InterruptionEventSourceTests(unittest.TestCase):
    def test_poll_once_emits_event_for_missing_primary_pane(self) -> None:
        source = InterruptionEventSource(
            _FakeRuntime(
                [
                    RegisteredPaneRef(
                        role="architect",
                        pane_id="%1",
                        scope="primary",
                        label="[architect] planning",
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
                        label="[coder] plan 2",
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
        self.assertEqual("[coder] plan 2", seen[0].payload["label"])

    def test_poll_once_ignores_expected_missing_pane(self) -> None:
        source = InterruptionEventSource(
            _FakeRuntime(
                [
                    RegisteredPaneRef(
                        role="architect",
                        pane_id="%1",
                        scope="primary",
                        label="[architect] planning",
                    )
                ],
                expected={"%1"},
            )
        )
        bus = EventBus()
        seen = []
        bus.register(seen.append)

        source.poll_once(bus)

        self.assertEqual([], seen)

    def test_poll_once_uses_plan_based_parallel_label_in_message(self) -> None:
        source = InterruptionEventSource(
            _FakeRuntime(
                [
                    RegisteredPaneRef(
                        role="coder",
                        pane_id="%9",
                        scope="parallel",
                        task_id=3,
                        label="[coder] API wiring",
                    )
                ]
            )
        )
        bus = EventBus()
        seen = []
        bus.register(seen.append)

        source.poll_once(bus)

        self.assertEqual("[coder] API wiring", seen[0].payload["label"])
        self.assertIn("Agent pane [coder] API wiring was closed or exited", seen[0].payload["message"])


if __name__ == "__main__":
    unittest.main()
