"""Phase handlers for the event-driven workflow router."""

from .architecting import ArchitectingHandler
from .completing import CompletingHandler
from .designing import DesigningHandler
from .failed import FailedHandler
from .fixing import FixingHandler
from .implementing import ImplementingHandler
from .planning import PlanningHandler
from .product_management import ProductManagementHandler
from .reviewing import ReviewingHandler

PHASE_HANDLERS = {
    "product_management": ProductManagementHandler(),
    "architecting": ArchitectingHandler(),
    "planning": PlanningHandler(),
    "designing": DesigningHandler(),
    "implementing": ImplementingHandler(),
    "reviewing": ReviewingHandler(),
    "fixing": FixingHandler(),
    "completing": CompletingHandler(),
    "failed": FailedHandler(),
}

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
