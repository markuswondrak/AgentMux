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


PHASE_CATALOG: tuple[PhaseEntry, ...] = (
    PhaseEntry("product_management", "01_product_management"),
    PhaseEntry("architecting", "02_planning"),
    PhaseEntry("planning", "02_planning"),
    PhaseEntry("designing", "04_design", optional=True),
    PhaseEntry("implementing", "05_implementation"),
    PhaseEntry("reviewing", "06_review"),
    PhaseEntry("fixing", "05_implementation", optional=True),
    PhaseEntry("completing", "08_completion"),
    PhaseEntry("failed", None, optional=True, in_pipeline=False),
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
