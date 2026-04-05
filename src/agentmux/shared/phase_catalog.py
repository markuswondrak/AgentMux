"""Phase catalog — Layer 1 of the unified phase abstraction.

Contains the ordered list of workflow phases with their filesystem directories
and monitor display flags. Importable from anywhere (no handler dependencies).

To add a new phase:
  1. Add a ``PhaseEntry`` here.
  2. Add a ``PhaseDescriptor`` in ``workflow/phase_registry.py``.
"""

from __future__ import annotations

from typing import NamedTuple


class PhaseEntry(NamedTuple):
    name: str
    dir_name: str | None  # None for virtual phases (failed) that have no directory
    optional: bool = False  # shown in monitor only when active
    in_pipeline: bool = True  # False for failed (not part of the display pipeline)
    monitor_file_patterns: tuple[str, ...] = ()  # fnmatch patterns for event log


_GLOBAL_FILE_PATTERNS: tuple[str, ...] = (
    "requirements.md",
    "03_research/code-*/summary.md",
    "03_research/code-*/detail.md",
    "03_research/code-*/done",
    "03_research/web-*/summary.md",
    "03_research/web-*/detail.md",
    "03_research/web-*/done",
)

PHASE_CATALOG: tuple[PhaseEntry, ...] = (
    PhaseEntry(
        "product_management",
        "01_product_management",
        monitor_file_patterns=("01_product_management/analysis.md",),
    ),
    PhaseEntry("architecting", "02_planning"),  # architecture.md not in monitor log
    PhaseEntry(
        "planning",
        "02_planning",
        monitor_file_patterns=("02_planning/plan.md", "02_planning/tasks.md"),
    ),
    PhaseEntry(
        "designing",
        "04_design",
        optional=True,
        monitor_file_patterns=("04_design/design.md",),
    ),
    PhaseEntry(
        "implementing",
        "05_implementation",
        monitor_file_patterns=("05_implementation/done_*",),
    ),
    PhaseEntry(
        "reviewing",
        "06_review",
        monitor_file_patterns=("06_review/review.md", "06_review/fix_request.md"),
    ),
    PhaseEntry(
        "fixing",
        "05_implementation",
        optional=True,
        monitor_file_patterns=("05_implementation/done_*",),
    ),
    PhaseEntry(
        "completing",
        "08_completion",
        monitor_file_patterns=(
            "08_completion/changes.md",
            "08_completion/approval.json",
        ),
    ),
    PhaseEntry("failed", None, optional=True, in_pipeline=False),
)

MONITOR_FILE_EVENT_PATTERNS: tuple[str, ...] = (
    *_GLOBAL_FILE_PATTERNS,
    *(pattern for entry in PHASE_CATALOG for pattern in entry.monitor_file_patterns),
)

# Phase-name → directory name mapping (derived from catalog).
SESSION_DIR_NAMES: dict[str, str] = {
    e.name: e.dir_name for e in PHASE_CATALOG if e.dir_name is not None
}
# Aliases used in _make_runtime_files() and other direct directory lookups.
SESSION_DIR_NAMES["research"] = "03_research"
SESSION_DIR_NAMES["design"] = "04_design"
SESSION_DIR_NAMES["implementation"] = "05_implementation"
SESSION_DIR_NAMES["review"] = "06_review"
SESSION_DIR_NAMES["completion"] = "08_completion"

# Phases hidden in the monitor unless they are the current active phase.
OPTIONAL_PHASES: frozenset[str] = frozenset(e.name for e in PHASE_CATALOG if e.optional)

# Ordered phase list shown in the monitor progress bar (includes terminal "done").
PIPELINE_STATES: list[str] = [e.name for e in PHASE_CATALOG if e.in_pipeline] + ["done"]

# Subset of PIPELINE_STATES that are always shown (non-optional phases + "done").
ALWAYS_VISIBLE_STATES: list[str] = [
    e.name for e in PHASE_CATALOG if e.in_pipeline and not e.optional
] + ["done"]
