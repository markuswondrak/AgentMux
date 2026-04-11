"""Base class for tool-event handlers.

Provides a ``_TOOL_HANDLERS`` registry pattern so concrete handlers only
declare their tool mappings once.  ``get_tool_specs()`` and
``handle_event()`` are implemented automatically.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from agentmux.workflow.event_router import ToolSpec, WorkflowEvent

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


@dataclass(frozen=True)
class ToolHandlerEntry:
    """Registry entry: logical event name, MCP tool names, and handler method."""

    name: str
    tool_names: tuple[str, ...]
    handler: Callable[
        [BaseToolHandler, WorkflowEvent, dict, PipelineContext],
        tuple[dict, str | None],
    ]


class BaseToolHandler:
    """Base class for phase handlers that process tool-call events.

    Subclasses define ``_TOOL_HANDLERS`` as a tuple of
    :class:`ToolHandlerEntry`.  The base class implements
    :meth:`get_tool_specs` and :meth:`handle_event` automatically.

    Example::

        class MyHandler(BaseToolHandler):
            _TOOL_HANDLERS: ClassVar[tuple[ToolHandlerEntry, ...]] = (
                ToolHandlerEntry(
                    name="done",
                    tool_names=("submit_done",),
                    handler=MyHandler._handle_done,
                ),
            )

            def _handle_done(self, event, state, ctx):
                return {}, None
    """

    _TOOL_HANDLERS: ClassVar[tuple[ToolHandlerEntry, ...]] = ()

    def get_tool_specs(self) -> Sequence[ToolSpec]:
        """Return ToolSpecs derived from _TOOL_HANDLERS."""
        return tuple(
            ToolSpec(name=entry.name, tool_names=entry.tool_names)
            for entry in self._TOOL_HANDLERS
        )

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Dispatch tool events to the registered handler method."""
        for entry in self._TOOL_HANDLERS:
            if event.kind == entry.name:
                return entry.handler(self, event, state, ctx)
        return {}, None
