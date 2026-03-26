from __future__ import annotations

import unittest

from agentmux import interruption_events


class InterruptionEventCatalogTests(unittest.TestCase):
    def test_legacy_events_canonicalize_to_shared_event_ids(self) -> None:
        self.assertEqual(
            interruption_events.INTERRUPTION_EVENT_CANCELED,
            interruption_events.canonical_interruption_event("keyboard_interrupt"),
        )
        self.assertEqual(
            interruption_events.INTERRUPTION_EVENT_FAILED,
            interruption_events.canonical_interruption_event("subprocess_error"),
        )
        self.assertEqual(
            interruption_events.INTERRUPTION_EVENT_FAILED,
            interruption_events.canonical_interruption_event("pipeline_exception"),
        )
        self.assertEqual(
            interruption_events.INTERRUPTION_EVENT_FAILED,
            interruption_events.canonical_interruption_event("orchestrator_exception"),
        )

    def test_category_and_fallback_cause_are_resolved_from_catalog(self) -> None:
        self.assertEqual(
            interruption_events.INTERRUPTION_CATEGORY_CANCELED,
            interruption_events.interruption_category_from_event("keyboard_interrupt"),
        )
        self.assertEqual(
            interruption_events.INTERRUPTION_CATEGORY_FAILED,
            interruption_events.interruption_category_from_event("pipeline_exception"),
        )
        self.assertEqual(
            "The pipeline hit an unexpected internal exception.",
            interruption_events.fallback_cause_from_event("pipeline_exception"),
        )
        self.assertEqual(
            "The pipeline stopped unexpectedly.",
            interruption_events.fallback_cause_from_event("unknown_event"),
        )

    def test_monitor_labels_and_report_titles_are_shared(self) -> None:
        self.assertEqual(
            "canceled by user",
            interruption_events.monitor_label_from_event("keyboard_interrupt"),
        )
        self.assertEqual(
            "run failed unexpectedly",
            interruption_events.monitor_label_from_event("run_failed"),
        )
        self.assertEqual(
            "Run canceled by user (Ctrl-C).",
            interruption_events.interruption_title_for_category(
                interruption_events.INTERRUPTION_CATEGORY_CANCELED
            ),
        )
        self.assertEqual(
            "Run failed unexpectedly.",
            interruption_events.interruption_title_for_category(
                interruption_events.INTERRUPTION_CATEGORY_FAILED
            ),
        )


if __name__ == "__main__":
    unittest.main()
