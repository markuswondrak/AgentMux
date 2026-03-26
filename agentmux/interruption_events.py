from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

INTERRUPTION_CATEGORY_CANCELED = "canceled"
INTERRUPTION_CATEGORY_FAILED = "failed"
INTERRUPTION_EVENT_CANCELED = "run_canceled"
INTERRUPTION_EVENT_FAILED = "run_failed"
DEFAULT_FALLBACK_CAUSE = "The pipeline stopped unexpectedly."

InterruptionCategory = Literal["canceled", "failed"]


@dataclass(frozen=True)
class InterruptionEventDefinition:
    canonical_event: str
    category: InterruptionCategory
    fallback_cause: str
    monitor_label: str


_EVENT_DEFINITIONS: dict[str, InterruptionEventDefinition] = {
    INTERRUPTION_EVENT_CANCELED: InterruptionEventDefinition(
        canonical_event=INTERRUPTION_EVENT_CANCELED,
        category=INTERRUPTION_CATEGORY_CANCELED,
        fallback_cause="The pipeline launcher was interrupted with Ctrl-C.",
        monitor_label="run canceled by user",
    ),
    "keyboard_interrupt": InterruptionEventDefinition(
        canonical_event=INTERRUPTION_EVENT_CANCELED,
        category=INTERRUPTION_CATEGORY_CANCELED,
        fallback_cause="The pipeline launcher was interrupted with Ctrl-C.",
        monitor_label="canceled by user",
    ),
    INTERRUPTION_EVENT_FAILED: InterruptionEventDefinition(
        canonical_event=INTERRUPTION_EVENT_FAILED,
        category=INTERRUPTION_CATEGORY_FAILED,
        fallback_cause="The pipeline failed unexpectedly.",
        monitor_label="run failed unexpectedly",
    ),
    "subprocess_error": InterruptionEventDefinition(
        canonical_event=INTERRUPTION_EVENT_FAILED,
        category=INTERRUPTION_CATEGORY_FAILED,
        fallback_cause="A required command failed while running the pipeline.",
        monitor_label="run failed",
    ),
    "pipeline_exception": InterruptionEventDefinition(
        canonical_event=INTERRUPTION_EVENT_FAILED,
        category=INTERRUPTION_CATEGORY_FAILED,
        fallback_cause="The pipeline hit an unexpected internal exception.",
        monitor_label="run failed",
    ),
    "orchestrator_exception": InterruptionEventDefinition(
        canonical_event=INTERRUPTION_EVENT_FAILED,
        category=INTERRUPTION_CATEGORY_FAILED,
        fallback_cause="The background orchestrator crashed unexpectedly.",
        monitor_label="orchestrator crashed",
    ),
}

_CANONICAL_EVENT_BY_CATEGORY: dict[InterruptionCategory, str] = {
    INTERRUPTION_CATEGORY_CANCELED: INTERRUPTION_EVENT_CANCELED,
    INTERRUPTION_CATEGORY_FAILED: INTERRUPTION_EVENT_FAILED,
}

_TITLE_BY_CATEGORY: dict[InterruptionCategory, str] = {
    INTERRUPTION_CATEGORY_CANCELED: "Run canceled by user (Ctrl-C).",
    INTERRUPTION_CATEGORY_FAILED: "Run failed unexpectedly.",
}


def _normalize_event_id(value: Any) -> str:
    return str(value).strip()


def normalize_interruption_category(value: Any) -> InterruptionCategory | None:
    normalized = str(value).strip().lower()
    if normalized == INTERRUPTION_CATEGORY_CANCELED:
        return INTERRUPTION_CATEGORY_CANCELED
    if normalized == INTERRUPTION_CATEGORY_FAILED:
        return INTERRUPTION_CATEGORY_FAILED
    return None


def canonical_event_for_category(category: InterruptionCategory) -> str:
    return _CANONICAL_EVENT_BY_CATEGORY[category]


def canonical_interruption_event(event_id: Any) -> str | None:
    normalized = _normalize_event_id(event_id)
    definition = _EVENT_DEFINITIONS.get(normalized)
    if definition is None:
        return None
    return definition.canonical_event


def interruption_category_from_event(event_id: Any) -> InterruptionCategory | None:
    normalized = _normalize_event_id(event_id)
    definition = _EVENT_DEFINITIONS.get(normalized)
    if definition is None:
        return None
    return definition.category


def fallback_cause_for_category(category: InterruptionCategory) -> str:
    canonical_event = canonical_event_for_category(category)
    return _EVENT_DEFINITIONS[canonical_event].fallback_cause


def fallback_cause_from_event(event_id: Any) -> str:
    normalized = _normalize_event_id(event_id)
    definition = _EVENT_DEFINITIONS.get(normalized)
    if definition is None:
        return DEFAULT_FALLBACK_CAUSE
    return definition.fallback_cause


def monitor_label_from_event(event_id: Any) -> str | None:
    normalized = _normalize_event_id(event_id)
    definition = _EVENT_DEFINITIONS.get(normalized)
    if definition is None:
        return None
    return definition.monitor_label


def interruption_title_for_category(category: InterruptionCategory) -> str:
    return _TITLE_BY_CATEGORY[category]
