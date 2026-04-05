"""Phase handlers for the event-driven workflow router."""

from __future__ import annotations

from typing import Any

# Individual handler classes (kept for direct imports in tests and other modules).
# PHASE_HANDLERS remains available here for backward compatibility, but it is
# resolved lazily to avoid a package import cycle with phase_registry.
from .architecting import ArchitectingHandler
from .completing import CompletingHandler
from .designing import DesigningHandler
from .failed import FailedHandler
from .fixing import FixingHandler
from .implementing import ImplementingHandler
from .planning import PlanningHandler
from .product_management import ProductManagementHandler
from .reviewing import ReviewingHandler

__all__ = [
    "PHASE_HANDLERS",
    "ArchitectingHandler",
    "ProductManagementHandler",
    "PlanningHandler",
    "DesigningHandler",
    "ImplementingHandler",
    "ReviewingHandler",
    "FixingHandler",
    "CompletingHandler",
    "FailedHandler",
]


def __getattr__(name: str) -> Any:
    if name == "PHASE_HANDLERS":
        from ..phase_registry import PHASE_HANDLERS

        return PHASE_HANDLERS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
