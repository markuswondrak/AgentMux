"""Centralized catalog of all valid workflow ``last_event`` values.

This module intentionally stores only event metadata. Phase-to-event wiring
lives in ``phase_registry.py`` so workflow relationships stay in one place.

This module has no dependencies on any other agentmux module — it imports only
from the Python standard library.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowEventDefinition:
    """Immutable descriptor for a workflow event."""

    name: str
    display_label: str
    description: str


# ---------------------------------------------------------------------------
# Event constants — values must match existing handler code verbatim
# ---------------------------------------------------------------------------

EVENT_FEATURE_CREATED: str = "feature_created"
EVENT_RESUMED: str = "resumed"
EVENT_PM_COMPLETED: str = "pm_completed"
EVENT_ARCHITECTURE_WRITTEN: str = "architecture_written"
EVENT_PLAN_WRITTEN: str = "plan_written"
EVENT_DESIGN_WRITTEN: str = "design_written"
EVENT_IMPLEMENTATION_COMPLETED: str = "implementation_completed"
EVENT_REVIEW_FAILED: str = "review_failed"
EVENT_REVIEW_PASSED: str = "review_passed"
EVENT_CHANGES_REQUESTED: str = "changes_requested"
EVENT_RUN_CANCELED: str = "run_canceled"
EVENT_RUN_FAILED: str = "run_failed"

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

WORKFLOW_EVENT_CATALOG: dict[str, WorkflowEventDefinition] = {
    EVENT_FEATURE_CREATED: WorkflowEventDefinition(
        name=EVENT_FEATURE_CREATED,
        display_label="starting up",
        description="A new feature session was created.",
    ),
    EVENT_RESUMED: WorkflowEventDefinition(
        name=EVENT_RESUMED,
        display_label="resumed",
        description="An interrupted session was resumed.",
    ),
    EVENT_PM_COMPLETED: WorkflowEventDefinition(
        name=EVENT_PM_COMPLETED,
        display_label="pm done",
        description="Product management phase completed.",
    ),
    EVENT_ARCHITECTURE_WRITTEN: WorkflowEventDefinition(
        name=EVENT_ARCHITECTURE_WRITTEN,
        display_label="architecture ready",
        description="Architect wrote architecture.md.",
    ),
    EVENT_PLAN_WRITTEN: WorkflowEventDefinition(
        name=EVENT_PLAN_WRITTEN,
        display_label="plan ready",
        description="Planner wrote plan.md, execution_plan.json, and plan_meta.json.",
    ),
    EVENT_DESIGN_WRITTEN: WorkflowEventDefinition(
        name=EVENT_DESIGN_WRITTEN,
        display_label="design ready",
        description="Designer wrote design.md.",
    ),
    EVENT_IMPLEMENTATION_COMPLETED: WorkflowEventDefinition(
        name=EVENT_IMPLEMENTATION_COMPLETED,
        display_label="code done",
        description="All implementation subplans completed.",
    ),
    EVENT_REVIEW_FAILED: WorkflowEventDefinition(
        name=EVENT_REVIEW_FAILED,
        display_label="fix needed",
        description="Reviewer issued a verdict:fail.",
    ),
    EVENT_REVIEW_PASSED: WorkflowEventDefinition(
        name=EVENT_REVIEW_PASSED,
        display_label="review passed",
        description="Reviewer issued a verdict:pass.",
    ),
    EVENT_CHANGES_REQUESTED: WorkflowEventDefinition(
        name=EVENT_CHANGES_REQUESTED,
        display_label="changes asked",
        description="User requested changes via the completion UI.",
    ),
    EVENT_RUN_CANCELED: WorkflowEventDefinition(
        name=EVENT_RUN_CANCELED,
        display_label="canceled",
        description="The pipeline run was canceled.",
    ),
    EVENT_RUN_FAILED: WorkflowEventDefinition(
        name=EVENT_RUN_FAILED,
        display_label="run failed",
        description="The pipeline run encountered a fatal error.",
    ),
}

VALID_LAST_EVENTS: frozenset[str] = frozenset(WORKFLOW_EVENT_CATALOG.keys())


def event_display_label(name: str) -> str:
    """Return the display label for a workflow event name.

    Falls back to ``name.replace("_", " ")`` for unknown event names.
    """
    entry = WORKFLOW_EVENT_CATALOG.get(name)
    if entry is not None:
        return entry.display_label
    return name.replace("_", " ")
