"""Phase handlers for the event-driven workflow router."""

from .product_management import ProductManagementHandler
from .planning import PlanningHandler
from .designing import DesigningHandler
from .implementing import ImplementingHandler
from .reviewing import ReviewingHandler
from .fixing import FixingHandler
from .completing import CompletingHandler
from .failed import FailedHandler

PHASE_HANDLERS = {
    "product_management": ProductManagementHandler(),
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
    "ProductManagementHandler",
    "PlanningHandler",
    "DesigningHandler",
    "ImplementingHandler",
    "ReviewingHandler",
    "FixingHandler",
    "CompletingHandler",
    "FailedHandler",
]
