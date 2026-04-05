"""Tests for workflow event catalog."""

from __future__ import annotations

import pytest

from agentmux.workflow.event_catalog import (
    EVENT_ARCHITECTURE_WRITTEN,
    EVENT_CHANGES_REQUESTED,
    EVENT_DESIGN_WRITTEN,
    EVENT_FEATURE_CREATED,
    EVENT_IMPLEMENTATION_COMPLETED,
    EVENT_PLAN_WRITTEN,
    EVENT_PM_COMPLETED,
    EVENT_RESUMED,
    EVENT_REVIEW_FAILED,
    EVENT_REVIEW_PASSED,
    EVENT_RUN_CANCELED,
    EVENT_RUN_FAILED,
    VALID_LAST_EVENTS,
    WORKFLOW_EVENT_CATALOG,
    WorkflowEventDefinition,
    event_display_label,
)
from agentmux.workflow.phase_registry import EVENT_EMITTERS

ALL_CONSTANTS = [
    EVENT_FEATURE_CREATED,
    EVENT_RESUMED,
    EVENT_PM_COMPLETED,
    EVENT_ARCHITECTURE_WRITTEN,
    EVENT_PLAN_WRITTEN,
    EVENT_DESIGN_WRITTEN,
    EVENT_IMPLEMENTATION_COMPLETED,
    EVENT_REVIEW_FAILED,
    EVENT_REVIEW_PASSED,
    EVENT_CHANGES_REQUESTED,
    EVENT_RUN_CANCELED,
    EVENT_RUN_FAILED,
]


class TestEventConstants:
    def test_all_constants_are_keys_in_catalog(self) -> None:
        """All 12 EVENT_* constants are keys in WORKFLOW_EVENT_CATALOG."""
        for const in ALL_CONSTANTS:
            assert const in WORKFLOW_EVENT_CATALOG, (
                f"{const!r} missing from WORKFLOW_EVENT_CATALOG"
            )

    def test_exactly_12_constants(self) -> None:
        assert len(ALL_CONSTANTS) == 12

    def test_constant_values(self) -> None:
        assert EVENT_FEATURE_CREATED == "feature_created"
        assert EVENT_RESUMED == "resumed"
        assert EVENT_PM_COMPLETED == "pm_completed"
        assert EVENT_ARCHITECTURE_WRITTEN == "architecture_written"
        assert EVENT_PLAN_WRITTEN == "plan_written"
        assert EVENT_DESIGN_WRITTEN == "design_written"
        assert EVENT_IMPLEMENTATION_COMPLETED == "implementation_completed"
        assert EVENT_REVIEW_FAILED == "review_failed"
        assert EVENT_REVIEW_PASSED == "review_passed"
        assert EVENT_CHANGES_REQUESTED == "changes_requested"
        assert EVENT_RUN_CANCELED == "run_canceled"
        assert EVENT_RUN_FAILED == "run_failed"


class TestValidLastEvents:
    def test_valid_last_events_equals_catalog_keys(self) -> None:
        """VALID_LAST_EVENTS equals frozenset(WORKFLOW_EVENT_CATALOG.keys())."""
        assert frozenset(WORKFLOW_EVENT_CATALOG.keys()) == VALID_LAST_EVENTS

    def test_valid_last_events_is_frozenset(self) -> None:
        assert isinstance(VALID_LAST_EVENTS, frozenset)

    def test_all_constants_in_valid_last_events(self) -> None:
        """No EVENT_* constant is silently missing from VALID_LAST_EVENTS."""
        for const in ALL_CONSTANTS:
            assert const in VALID_LAST_EVENTS, (
                f"{const!r} missing from VALID_LAST_EVENTS"
            )


class TestWorkflowEventDefinition:
    def test_definition_name_matches_key(self) -> None:
        """Every WorkflowEventDefinition in the catalog has name matching its key."""
        for key, defn in WORKFLOW_EVENT_CATALOG.items():
            assert defn.name == key, f"Catalog entry for {key!r} has name={defn.name!r}"

    def test_definition_is_frozen_dataclass(self) -> None:
        defn = WORKFLOW_EVENT_CATALOG[EVENT_FEATURE_CREATED]
        assert isinstance(defn, WorkflowEventDefinition)
        with pytest.raises((AttributeError, TypeError)):
            defn.name = "something_else"  # type: ignore[misc]

    def test_definition_contains_only_event_metadata_fields(self) -> None:
        assert tuple(WorkflowEventDefinition.__dataclass_fields__) == (
            "name",
            "display_label",
            "description",
        )

    def test_definition_does_not_expose_phase_relationship_fields(self) -> None:
        for defn in WORKFLOW_EVENT_CATALOG.values():
            assert not hasattr(defn, "consumed_by")
            assert not hasattr(defn, "transitions_to")

    def test_display_label_values(self) -> None:
        expected = {
            EVENT_FEATURE_CREATED: "starting up",
            EVENT_RESUMED: "resumed",
            EVENT_PM_COMPLETED: "pm done",
            EVENT_ARCHITECTURE_WRITTEN: "architecture ready",
            EVENT_PLAN_WRITTEN: "plan ready",
            EVENT_DESIGN_WRITTEN: "design ready",
            EVENT_IMPLEMENTATION_COMPLETED: "code done",
            EVENT_REVIEW_FAILED: "fix needed",
            EVENT_REVIEW_PASSED: "review passed",
            EVENT_CHANGES_REQUESTED: "changes asked",
            EVENT_RUN_CANCELED: "canceled",
            EVENT_RUN_FAILED: "run failed",
        }
        for const, label in expected.items():
            assert WORKFLOW_EVENT_CATALOG[const].display_label == label, (
                f"{const!r}: expected {label!r}"
            )


class TestEventDisplayLabel:
    def test_known_name_returns_catalog_label(self) -> None:
        """event_display_label() returns catalog display_label for known names."""
        assert event_display_label(EVENT_FEATURE_CREATED) == "starting up"
        assert event_display_label(EVENT_PLAN_WRITTEN) == "plan ready"
        assert event_display_label(EVENT_REVIEW_FAILED) == "fix needed"

    def test_unknown_name_falls_back_to_replace(self) -> None:
        """event_display_label() falls back to underscore-to-space for unknown names."""
        assert event_display_label("unknown_event_xyz") == "unknown event xyz"

    def test_fallback_for_empty_string(self) -> None:
        assert event_display_label("") == ""

    def test_fallback_for_fabricated_labels(self) -> None:
        """Previously fabricated labels no longer exist in catalog."""
        assert event_display_label("plan_approved") == "plan approved"
        assert event_display_label("review_written") == "review written"


class TestPhaseEventWiring:
    def test_event_emitters_are_derived_from_phase_registry(self) -> None:
        assert EVENT_EMITTERS == {
            EVENT_PM_COMPLETED: ("product_management",),
            EVENT_ARCHITECTURE_WRITTEN: ("architecting",),
            EVENT_PLAN_WRITTEN: ("planning",),
            EVENT_DESIGN_WRITTEN: ("designing",),
            EVENT_IMPLEMENTATION_COMPLETED: ("implementing", "fixing"),
            EVENT_REVIEW_FAILED: ("reviewing",),
            EVENT_REVIEW_PASSED: ("reviewing",),
            EVENT_CHANGES_REQUESTED: ("completing",),
        }


class TestValidateLastEvent:
    """Tests for validate_last_event() from phase_helpers."""

    def test_valid_event_feature_created_does_not_raise(self) -> None:
        from agentmux.workflow.phase_helpers import validate_last_event

        validate_last_event("feature_created")  # Should not raise

    def test_valid_event_run_failed_does_not_raise(self) -> None:
        from agentmux.workflow.phase_helpers import validate_last_event

        validate_last_event("run_failed")  # Should not raise

    def test_bogus_event_raises_value_error(self) -> None:
        from agentmux.workflow.phase_helpers import validate_last_event

        with pytest.raises(ValueError, match="Unknown last_event"):
            validate_last_event("bogus_event")

    def test_empty_string_raises_value_error(self) -> None:
        from agentmux.workflow.phase_helpers import validate_last_event

        with pytest.raises(ValueError, match="Unknown last_event"):
            validate_last_event("")

    def test_fabricated_plan_approved_raises(self) -> None:
        from agentmux.workflow.phase_helpers import validate_last_event

        with pytest.raises(ValueError, match="Unknown last_event"):
            validate_last_event("plan_approved")

    def test_fabricated_review_written_raises(self) -> None:
        from agentmux.workflow.phase_helpers import validate_last_event

        with pytest.raises(ValueError, match="Unknown last_event"):
            validate_last_event("review_written")
