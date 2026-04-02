from __future__ import annotations

import unittest

import agentmux.workflow.interruptions as interruption_events


class InterruptionEventCatalogTests(unittest.TestCase):
    def test_only_canonical_events_are_recognized(self) -> None:
        self.assertEqual(
            interruption_events.INTERRUPTION_EVENT_CANCELED,
            interruption_events.canonical_interruption_event("run_canceled"),
        )
        self.assertEqual(
            interruption_events.INTERRUPTION_EVENT_FAILED,
            interruption_events.canonical_interruption_event("run_failed"),
        )
        self.assertIsNone(
            interruption_events.canonical_interruption_event("keyboard_interrupt")
        )

    def test_category_and_fallback_cause_are_resolved_from_catalog(self) -> None:
        self.assertEqual(
            interruption_events.INTERRUPTION_CATEGORY_CANCELED,
            interruption_events.interruption_category_from_event("run_canceled"),
        )
        self.assertEqual(
            interruption_events.INTERRUPTION_CATEGORY_FAILED,
            interruption_events.interruption_category_from_event("run_failed"),
        )
        self.assertEqual(
            "The pipeline failed unexpectedly.",
            interruption_events.fallback_cause_from_event("run_failed"),
        )
        self.assertEqual(
            "The pipeline stopped unexpectedly.",
            interruption_events.fallback_cause_from_event("unknown_event"),
        )

    def test_monitor_labels_and_report_titles_are_shared(self) -> None:
        self.assertEqual(
            "run canceled by user",
            interruption_events.monitor_label_from_event("run_canceled"),
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
