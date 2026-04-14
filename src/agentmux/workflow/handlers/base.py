"""Base class for tool-event handlers.

Provides a ``_get_tool_handlers()`` method so concrete handlers can
build their tool mappings dynamically (e.g. with role-specific closures).
``get_tool_specs()`` and ``handle_event()`` are implemented automatically.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

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

    Subclasses override :meth:`_get_tool_handlers` to return a tuple of
    :class:`ToolHandlerEntry`.  The base class implements
    :meth:`get_tool_specs` and :meth:`handle_event` automatically.

    Example::

        class MyHandler(BaseToolHandler):
            def _get_tool_handlers(self):
                return (
                    ToolHandlerEntry(
                        name="done",
                        tool_names=("submit_done",),
                        handler=MyHandler._handle_done,
                    ),
                )

            def _handle_done(self, event, state, ctx):
                return {}, None
    """

    def _get_tool_handlers(self) -> tuple[ToolHandlerEntry, ...]:
        """Return the tuple of ToolHandlerEntry for this handler."""
        return ()

    def get_tool_specs(self) -> Sequence[ToolSpec]:
        """Return ToolSpecs derived from _get_tool_handlers()."""
        return tuple(
            ToolSpec(name=entry.name, tool_names=entry.tool_names)
            for entry in self._get_tool_handlers()
        )

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Dispatch tool events to the registered handler method."""
        for entry in self._get_tool_handlers():
            if event.kind == entry.name:
                return entry.handler(self, event, state, ctx)
        return {}, None
