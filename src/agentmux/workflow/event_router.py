"""Event-driven workflow router infrastructure.

This module provides the core infrastructure for the event-driven orchestrator
refactor. It defines the event types, handler protocol, and router that
routes events to phase-specific handlers.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .transitions import PipelineContext


@dataclass(frozen=True)
class EventSpec:
    """Declarative specification of a workflow event.

    An event fires when any file matching ``watch_paths`` is created or
    modified **and** ``is_ready`` returns True.  This decouples the logical
    event (e.g. "review is complete") from the raw OS file signal, so
    streamed/incremental writes are handled correctly: the event won't fire
    until the content actually satisfies the condition, regardless of how
    many ``file.created`` / ``file.activity`` signals preceded it.

    Attributes:
        name:        Logical event name dispatched to ``handle_event``.
        watch_paths: Glob patterns (relative to feature dir); any
                     ``file.created`` or ``file.activity`` on a matching path
                     triggers ``is_ready`` evaluation.
        is_ready:    ``(triggering_path, ctx, state) -> bool``
                     Return True when the event should fire.
    """

    name: str
    watch_paths: tuple[str, ...]
    is_ready: Callable[[str, PipelineContext, dict], bool]


@dataclass(frozen=True)
class WorkflowEvent:
    """Normalized event for the workflow router.

    Attributes:
        kind: Event type - "file.created", "file.activity", "interruption.pane_exited"
        path: Relative path for file events
            (e.g., "planning/plan.md"), None for interruptions
        payload: Additional context (pane details for interruptions, empty for files)
    """

    kind: str
    path: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    """Declarative specification for routing tool-call events.

    When a ``SessionEvent`` with ``kind="tool.<bare_name>"`` arrives, the
    router checks each ``ToolSpec`` returned by the handler's
    ``get_tool_specs()``.  If ``bare_name`` is in ``tool_names``, the event
    is dispatched to ``handle_event`` with ``kind=spec.name``.

    Attributes:
        name: Logical event name dispatched to ``handle_event``.
        tool_names: Bare MCP tool names to match (without the "tool." prefix).
    """

    name: str
    tool_names: tuple[str, ...]


@runtime_checkable
class PhaseHandler(Protocol):
    """Protocol for phase-specific event handling.

    Each phase (planning, implementing, etc.) implements this protocol.
    The router calls enter() once per phase, then handle_event() for each event.

    Handlers declare their events via ``get_event_specs()``.  When a handler
    returns non-empty specs, the router evaluates them on every
    ``file.created`` / ``file.activity`` event and only calls ``handle_event``
    when a spec's ``is_ready`` predicate returns True.  The ``event.kind``
    passed to ``handle_event`` will be the spec's logical name (not the raw
    ``"file.created"`` / ``"file.activity"`` string), while ``event.path``
    carries the triggering file path for topic extraction etc.

    Handlers that return empty specs receive raw ``WorkflowEvent`` objects
    as before (backward-compatible fallback).
    """

    def enter(self, state: dict, ctx: PipelineContext) -> dict:
        """Called once when entering the phase.

        Responsibilities:
        - Send initial prompt to the appropriate agent
        - Initialize phase-specific state fields
        - NOT write state to disk (router handles this)

        Args:
            state: Current state dict (read-only, don't mutate)
            ctx: Pipeline context with files, runtime, agents

        Returns:
            Dict of state updates to apply (e.g., {"subplan_count": 3})
        """
        ...

    def get_event_specs(self) -> Sequence[EventSpec]:
        """Return the event specs this handler cares about.

        Returns:
            Sequence of EventSpec objects.  Return empty sequence (or don't
            override) to receive raw WorkflowEvents in handle_event instead.
        """
        ...

    def get_tool_specs(self) -> Sequence[ToolSpec]:
        """Return ToolSpecs for MCP tool-call events.

        Returns:
            Sequence of ToolSpec objects.  Return empty sequence (or don't
            override) to have tool.* events return ({}, None).
        """
        ...

    def handle_event(
        self, event: WorkflowEvent, state: dict, ctx: PipelineContext
    ) -> tuple[dict, str | None]:
        """Handle an event for this phase.

        Responsibilities:
        - Check if event is relevant (path matching, content parsing)
        - Perform actions (notify agents, dispatch tasks, etc.)
        - NOT write state to disk (router handles this)

        Args:
            event: The workflow event to process.  For spec-based handlers,
                   ``event.kind`` is the logical spec name and ``event.path``
                   is the triggering file path.
            state: Current state dict (read-only, don't mutate)
            ctx: Pipeline context

        Returns:
            Tuple of (state_updates, next_phase_or_None)
            - state_updates: Dict to merge into state
            - next_phase: String like "implementing" to transition, or None to stay
            - Special: return ({"__exit__": 0}, None) for success exit
            - Special: return ({"__exit__": 1}, None) for failure exit
        """
        ...


def path_matches(pattern: str, path: str) -> bool:
    """Check if a path matches a glob pattern.

    Args:
        pattern: Glob pattern like "research/code-*/request.md"
        path: Relative path like "research/code-auth/request.md"

    Returns:
        True if path matches pattern
    """
    return fnmatch.fnmatch(path, pattern)


def path_matches_any(patterns: list[str], path: str) -> bool:
    """Check if a path matches any of the given patterns."""
    return any(path_matches(p, path) for p in patterns)


class WorkflowEventRouter:
    """Routes events to phase handlers based on current phase.

    Responsibilities:
    - Track which phases have been entered
    - Route events to the current phase's handler
    - Apply state updates from handlers
    - Handle phase transitions
    - Detect exit signals
    """

    EXIT_SUCCESS = 0
    EXIT_FAILURE = 1

    def __init__(self, phases: dict[str, PhaseHandler]):
        """Initialize router with phase handlers.

        Args:
            phases: Map of phase name to handler instance
                   e.g., {"planning": PlanningHandler(), ...}
        """
        self._phases = phases
        self._entered: set[str] = set()

    def enter_current_phase(self, state: dict, ctx: PipelineContext) -> dict:
        phase_name = state.get("phase", "")
        handler = self._phases.get(phase_name)
        if handler is None or phase_name in self._entered:
            return {}

        enter_updates = handler.enter(state, ctx)
        state.update(enter_updates)
        self._entered.add(phase_name)

        from ..sessions.state_store import write_state

        write_state(ctx.files.state, state)
        return enter_updates

    def handle(
        self, event: WorkflowEvent, state: dict, ctx: PipelineContext
    ) -> tuple[dict, int | None]:
        """Route event to current phase handler.

        This is the main entry point called by the orchestrator for each event.

        Args:
            event: The workflow event
            state: Current state dict (will be mutated with updates)
            ctx: Pipeline context

        Returns:
            Tuple of (state_updates, exit_code_or_None)
            - state_updates: Dict that was applied to state
            - exit_code: 0 for success, 1 for failure, None to continue
        """
        phase_name = state.get("phase", "")
        handler = self._phases.get(phase_name)

        if handler is None:
            # Unknown phase - log warning, return empty
            return {}, None

        # Enter phase once
        if phase_name not in self._entered:
            self.enter_current_phase(state, ctx)

        # Dispatch event: via specs if declared, otherwise raw
        updates, next_phase = self._dispatch(event, handler, state, ctx)

        # Check for exit signal
        exit_code = updates.pop("__exit__", None)
        if exit_code is not None:
            state.update(updates)
            return updates, exit_code

        # Apply updates
        state.update(updates)

        # Phase transition?
        if next_phase is not None:
            self._entered.discard(phase_name)
            state["phase"] = next_phase
            state["updated_at"] = self._now_iso()
            state["updated_by"] = "pipeline"
            from ..sessions.state_store import write_state

            write_state(ctx.files.state, state)

            # Recursively enter new phase with same event
            # (allows immediate transition without waiting for next event)
            return self.handle(event, state, ctx)

        # Write state if there were updates
        if updates:
            from ..sessions.state_store import write_state

            write_state(ctx.files.state, state)

        return updates, None

    def _dispatch(
        self,
        event: WorkflowEvent,
        handler: Any,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        """Route a file event to the handler via specs or directly.

        If the handler declares EventSpecs, evaluate them:
        - Only ``file.created`` and ``file.activity`` events are considered.
        - For each spec whose watch_paths matches the event path, call
          ``is_ready``.  If ready, dispatch a logical WorkflowEvent with
          ``kind=spec.name`` to ``handle_event`` and return.
        - If no spec fires, return ``{}, None``.

        Handlers without specs receive the raw WorkflowEvent unchanged.

        Tool-call events (``tool.*``) are routed via ``ToolSpec``:
        - If the handler declares ``get_tool_specs()``, match the bare tool
          name against each spec's ``tool_names``.  On match, dispatch a
          ``WorkflowEvent(kind=spec.name, payload=event.payload)``.
        - Non-matching tool names return ``{}, None``.
        """
        # Route tool.* events via ToolSpec
        if event.kind.startswith("tool."):
            get_tool_specs = getattr(handler, "get_tool_specs", None)
            if get_tool_specs is not None:
                bare_name = event.kind[len("tool.") :]
                for spec in get_tool_specs():
                    if bare_name in spec.tool_names:
                        logical = WorkflowEvent(kind=spec.name, payload=event.payload)
                        return handler.handle_event(logical, state, ctx)
            return {}, None

        # Route file events via EventSpec or raw
        get_specs = getattr(handler, "get_event_specs", None)
        if get_specs is None:
            # Legacy handler without specs — pass raw event through
            return handler.handle_event(event, state, ctx)

        specs = list(get_specs())
        if not specs:
            # Handler explicitly opts out of spec routing — raw event
            return handler.handle_event(event, state, ctx)

        if event.kind not in ("file.created", "file.activity"):
            return {}, None

        path = event.path
        if path is None:
            return {}, None

        for spec in specs:
            if not any(fnmatch.fnmatch(path, p) for p in spec.watch_paths):
                continue
            if spec.is_ready(path, ctx, state):
                logical = WorkflowEvent(kind=spec.name, path=path)
                return handler.handle_event(logical, state, ctx)

        return {}, None

    @staticmethod
    def _now_iso() -> str:
        """Get current timestamp in ISO format."""
        return datetime.now().astimezone().isoformat(timespec="seconds")


def extract_research_topic(path: str, prefix: str) -> str | None:
    """Extract topic from research directory path.

    Args:
        path: Relative path like "03_research/code-auth/request.md"
        prefix: Either "code-" or "web-"

    Returns:
        Topic string like "auth", or None if path doesn't match
    """
    match = re.match(rf"^03_research/{prefix}([^/]+)/", path)
    if match:
        return match.group(1)
    return None


def extract_subplan_index(path: str) -> int | None:
    """Extract subplan index from done marker path.

    Args:
        path: Relative path like "05_implementation/done_3"

    Returns:
        Integer index like 3, or None if path doesn't match
    """
    match = re.match(r"^\d{2}_implementation/done_(\d+)$", path)
    if match:
        return int(match.group(1))
    return None
