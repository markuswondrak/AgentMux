"""Phase registry — Layer 2 of the unified phase abstraction.

Combines the directory catalog from ``shared.phase_catalog`` with handler
classes, primary roles, and resume-check logic into ``PHASE_REGISTRY``.

To add a new phase:
  1. Create ``workflow/handlers/<phase>.py`` with a handler class.
  2. Add a ``PhaseEntry`` in ``shared/phase_catalog.py``.
  3. Add a ``PhaseDescriptor`` here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .event_catalog import (
    EVENT_ARCHITECTURE_WRITTEN,
    EVENT_CHANGES_REQUESTED,
    EVENT_DESIGN_WRITTEN,
    EVENT_IMPLEMENTATION_COMPLETED,
    EVENT_PLAN_WRITTEN,
    EVENT_PM_COMPLETED,
    EVENT_REVIEW_FAILED,
    EVENT_REVIEW_PASSED,
    EVENT_VALIDATION_FAILED,
    EVENT_VALIDATION_PASSED,
    WORKFLOW_EVENT_CATALOG,
)
from .handlers.architecting import ArchitectingHandler
from .handlers.completing import CompletingHandler
from .handlers.designing import DesigningHandler
from .handlers.failed import FailedHandler
from .handlers.fixing import FixingHandler
from .handlers.implementing import ImplementingHandler
from .handlers.planning import PlanningHandler
from .handlers.product_management import ProductManagementHandler
from .handlers.reviewing import ReviewingHandler
from .handlers.validating import ValidatingHandler
from .handoff_artifacts import review_yaml_has_verdict
from .phase_helpers import select_reviewer_roles

# ---------------------------------------------------------------------------
# Resume-check helpers (extracted from sessions/state_store.infer_resume_phase)
# ---------------------------------------------------------------------------


def _pm_done(feature_dir: Path, state: dict[str, Any]) -> bool:
    """True if the PM phase is not enabled or a downstream artifact exists.

    PM completion is signalled via the submit_pm_done MCP tool call, which
    transitions state.json to the next phase. No done-marker file is written.
    We use architecture.md as a proxy: if it exists, the architect has started
    and PM is unambiguously done.
    """
    if not bool(state.get("product_manager")):
        return True  # Phase not requested for this run
    return (feature_dir / "02_architecting" / "architecture.md").exists()


def _first_available_role(roles: tuple[str, ...], agents: dict[str, Any]) -> str | None:
    for role in roles:
        if role in agents:
            return role
    return None


def _implementing_done(feature_dir: Path, state: dict[str, Any]) -> bool:
    """True when all implementation subplans have their done_N marker.

    Returns True immediately when in a fixing iteration (fix_request.md exists
    and review_iteration > 0), so that the registry walk skips to the fixing
    phase check rather than incorrectly returning "implementing".
    """
    review_dir = feature_dir / "07_review"
    fix_iteration = (review_dir / "fix_request.md").exists() and int(
        state.get("review_iteration", 0)
    ) > 0
    if fix_iteration:
        return True  # Implementing phase is past; fixing phase handles this iteration

    implementation_dir = feature_dir / "06_implementation"
    subplan_count_raw = state.get("subplan_count")
    try:
        subplan_count = int(subplan_count_raw)
    except (TypeError, ValueError):
        subplan_count = 0
    if subplan_count < 0:
        subplan_count = 0

    if subplan_count > 0:
        return all(
            (implementation_dir / f"done_{i}").exists()
            for i in range(1, subplan_count + 1)
        )
    return any(implementation_dir.glob("done_*"))


def _reviewing_done(feature_dir: Path, state: dict[str, Any]) -> bool:
    """True when the reviewing phase has completed.

    In a fix iteration review output is processed and deleted before transitioning
    to fixing. We use fix_request.md + done_1 presence to distinguish:
    - done_1 missing → review ran, fix needed → reviewing IS done
    - done_1 exists  → fix applied, follow-up review pending → reviewing NOT done
    """
    review_dir = feature_dir / "07_review"
    if (review_dir / "review.md").exists() or review_yaml_has_verdict(review_dir):
        return True  # Reviewer wrote output; orchestrator may not have processed it yet
    fix_iteration = (review_dir / "fix_request.md").exists() and int(
        state.get("review_iteration", 0)
    ) > 0
    if fix_iteration:
        return not (feature_dir / "06_implementation" / "done_1").exists()
    return False


def _fixing_done(feature_dir: Path, state: dict[str, Any]) -> bool:
    """True when the fixing phase is complete or not applicable.

    Fixing only applies when fix_request.md exists and review_iteration > 0.
    """
    review_dir = feature_dir / "07_review"
    in_fix_iteration = (review_dir / "fix_request.md").exists() and int(
        state.get("review_iteration", 0)
    ) > 0
    if not in_fix_iteration:
        return True  # Not in a fix iteration — phase not needed
    return (feature_dir / "06_implementation" / "done_1").exists()


def _validating_done(feature_dir: Path, state: dict[str, Any]) -> bool:
    """True when automated validation finished or is not configured."""

    from ..configuration import infer_project_dir, load_layered_config  # noqa: PLC0415

    try:
        project_dir = infer_project_dir(feature_dir)
        cfg = load_layered_config(project_dir)
        commands = cfg.workflow_settings.validation.commands
    except (OSError, ValueError):
        commands = ()
    if not commands:
        return True

    result_path = feature_dir / "06_implementation" / "validation_result.json"
    if not result_path.exists():
        return False

    try:
        raw = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False

    passed = raw.get("passed")
    if passed is True:
        return True
    if passed is False:
        done_after_fix = (feature_dir / "06_implementation" / "done_1").exists()
        return not done_after_fix
    return False


def _designing_needed_and_done(feature_dir: Path, state: dict[str, Any]) -> bool:
    """True when the design artifact exists (or the phase is not needed)."""
    import yaml

    ep_path = feature_dir / "04_planning" / "execution_plan.yaml"
    if not ep_path.exists():
        return True  # No execution plan → designing not needed → treat as done
    try:
        data: dict[str, Any] = yaml.safe_load(ep_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return True
    if not isinstance(data, dict) or not bool(data.get("needs_design")):
        return True  # Phase not required for this run
    return (feature_dir / "05_design" / "design.md").exists()


def _reviewing_startup_role(
    feature_dir: Path, state: dict[str, Any], agents: dict[str, Any]
) -> str | None:
    _ = feature_dir
    reviewer_roles = select_reviewer_roles(state)
    reviewer_role = reviewer_roles[0] if reviewer_roles else "reviewer_logic"
    if reviewer_role in agents:
        return reviewer_role
    return None


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


StartupRoleResolver = Callable[[Path, dict[str, Any], dict[str, Any]], str | None]


@dataclass(frozen=True)
class ResumeCheck:
    """Encodes how to determine whether a phase is complete during resume."""

    # Relative path (from feature_dir) that must exist for the phase to be done.
    completion_artifact: str | None = None
    # Callable for phases whose completion cannot be expressed as a single file.
    custom: Callable[[Path, dict[str, Any]], bool] | None = None


@dataclass(frozen=True)
class PhaseDescriptor:
    """Everything a phase knows about itself.

    Attributes:
        name: Workflow phase name (matches PHASE_CATALOG and state.json).
        dir_name: Feature-relative directory, or None for virtual phases.
        handler_class: The handler class for this phase (not an instance).
        primary_roles: Agent roles activated during this phase.
        resume_check: Logic for infer_resume_phase().
        research_owner: Role notified when a batch researcher crashes in this phase.
        emitted_events: Single source of truth for the events this phase emits.
    """

    name: str
    dir_name: str | None
    handler_class: type
    primary_roles: tuple[str, ...]
    resume_check: ResumeCheck = field(default_factory=ResumeCheck)
    research_owner: str | None = None
    startup_role_resolver: StartupRoleResolver | None = None
    emitted_events: tuple[str, ...] = field(default_factory=tuple)

    def resolve_startup_role(
        self, feature_dir: Path, state: dict[str, Any], agents: dict[str, Any]
    ) -> str | None:
        if self.startup_role_resolver is not None:
            role = self.startup_role_resolver(feature_dir, state, agents)
            if role is not None:
                return role
        return _first_available_role(self.primary_roles, agents)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PHASE_REGISTRY: tuple[PhaseDescriptor, ...] = (
    PhaseDescriptor(
        name="product_management",
        dir_name="01_product_management",
        handler_class=ProductManagementHandler,
        primary_roles=("product-manager",),
        resume_check=ResumeCheck(custom=_pm_done),
        research_owner="product-manager",
        emitted_events=(EVENT_PM_COMPLETED,),
    ),
    PhaseDescriptor(
        name="architecting",
        dir_name="02_architecting",
        handler_class=ArchitectingHandler,
        primary_roles=("architect",),
        resume_check=ResumeCheck(completion_artifact="02_architecting/architecture.md"),
        research_owner="architect",
        emitted_events=(EVENT_ARCHITECTURE_WRITTEN,),
    ),
    PhaseDescriptor(
        name="planning",
        dir_name="04_planning",
        handler_class=PlanningHandler,
        primary_roles=("planner",),
        resume_check=ResumeCheck(completion_artifact="04_planning/plan.yaml"),
        research_owner="architect",
        emitted_events=(EVENT_PLAN_WRITTEN,),
    ),
    PhaseDescriptor(
        name="designing",
        dir_name="05_design",
        handler_class=DesigningHandler,
        primary_roles=("designer",),
        resume_check=ResumeCheck(custom=_designing_needed_and_done),
        emitted_events=(EVENT_DESIGN_WRITTEN,),
    ),
    PhaseDescriptor(
        name="implementing",
        dir_name="06_implementation",
        handler_class=ImplementingHandler,
        primary_roles=("coder",),
        resume_check=ResumeCheck(custom=_implementing_done),
        research_owner="architect",
        emitted_events=(EVENT_IMPLEMENTATION_COMPLETED,),
    ),
    PhaseDescriptor(
        name="validating",
        dir_name="06_implementation",
        handler_class=ValidatingHandler,
        primary_roles=(),
        resume_check=ResumeCheck(custom=_validating_done),
        emitted_events=(EVENT_VALIDATION_PASSED, EVENT_VALIDATION_FAILED),
    ),
    PhaseDescriptor(
        name="reviewing",
        dir_name="07_review",
        handler_class=ReviewingHandler,
        primary_roles=(
            "reviewer",
            "reviewer_logic",
            "reviewer_quality",
            "reviewer_expert",
        ),
        resume_check=ResumeCheck(custom=_reviewing_done),
        startup_role_resolver=_reviewing_startup_role,
        emitted_events=(EVENT_REVIEW_FAILED, EVENT_REVIEW_PASSED),
    ),
    PhaseDescriptor(
        name="fixing",
        dir_name="06_implementation",
        handler_class=FixingHandler,
        primary_roles=("coder",),
        resume_check=ResumeCheck(custom=_fixing_done),
        emitted_events=(EVENT_IMPLEMENTATION_COMPLETED,),
    ),
    PhaseDescriptor(
        name="completing",
        dir_name="08_completion",
        handler_class=CompletingHandler,
        primary_roles=("reviewer",),
        resume_check=ResumeCheck(),
        emitted_events=(EVENT_CHANGES_REQUESTED,),
    ),
    PhaseDescriptor(
        name="failed",
        dir_name=None,
        handler_class=FailedHandler,
        primary_roles=(),
        resume_check=ResumeCheck(),
    ),
)

PHASE_EVENT_LABELS: dict[str, str] = {
    name: defn.display_label for name, defn in WORKFLOW_EVENT_CATALOG.items()
}

# ---------------------------------------------------------------------------
# Derived lookups (replace previous scattered dicts)
# ---------------------------------------------------------------------------

# Reverse lookup derived from ``PhaseDescriptor.emitted_events`` so callers can
# answer "which phases emit this event?" without reintroducing duplicated wiring.
_event_emitters: dict[str, list[str]] = {}
for descriptor in PHASE_REGISTRY:
    for event_name in descriptor.emitted_events:
        _event_emitters.setdefault(event_name, []).append(descriptor.name)

EVENT_EMITTERS: dict[str, tuple[str, ...]] = {
    name: tuple(phase_names) for name, phase_names in _event_emitters.items()
}

# Replaces PHASE_HANDLERS in workflow/handlers/__init__.py.
# Instances are created once at import time (same behaviour as before).
PHASE_HANDLERS: dict[str, Any] = {p.name: p.handler_class() for p in PHASE_REGISTRY}

PHASE_BY_NAME: dict[str, PhaseDescriptor] = {p.name: p for p in PHASE_REGISTRY}


def resolve_phase_startup_role(
    phase_name: str,
    feature_dir: Path,
    state: dict[str, Any],
    agents: dict[str, Any],
) -> str | None:
    descriptor = PHASE_BY_NAME.get(phase_name)
    if descriptor is None:
        return None
    return descriptor.resolve_startup_role(feature_dir, state, agents)


# Maps phase name → research-owning role for _determine_research_owner().
PHASE_RESEARCH_OWNERS: dict[str, str] = {
    p.name: p.research_owner for p in PHASE_REGISTRY if p.research_owner is not None
}
