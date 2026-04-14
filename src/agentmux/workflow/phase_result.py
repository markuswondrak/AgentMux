"""Phase result types for workflow handlers.

This module defines the PhaseResult NamedTuple used by all phase handlers
for their enter() method return type.
"""

from __future__ import annotations

from typing import NamedTuple


class PhaseResult(NamedTuple):
    """Uniform return type for handler enter() methods.

    Attributes:
        updates: Dict of state updates to apply.
        next_phase: Optional phase name to transition to immediately.
    """

    updates: dict
    next_phase: str | None = None
