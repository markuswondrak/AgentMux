"""Phase handlers for the event-driven workflow router."""

# Individual handler classes (kept for direct imports in tests and other modules).
# PHASE_HANDLERS is now derived from the phase registry — a single source of truth.
# Import it from there rather than maintaining a duplicate mapping here.
from ..phase_registry import PHASE_HANDLERS as PHASE_HANDLERS  # noqa: F401
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
