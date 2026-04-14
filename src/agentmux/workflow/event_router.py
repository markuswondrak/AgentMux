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
from typing import Any, NamedTuple, Protocol, runtime_checkable

from .transitions import PipelineContext


class PhaseResult(NamedTuple):
    """Uniform return type for handler enter() methods.

    Attributes:
        updates: Dict of state updates to apply.
        next_phase: Optional phase name to transition to immediately.
    """

    updates: dict
    next_phase: str | None = None


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

    Empty ``get_event_specs()`` means no file events are dispatched.
    For catch-all behaviour (e.g. terminal error handler):
    ``EventSpec(name=..., watch_paths=('*',), ...)``.
    """

    def enter(self, state: dict, ctx: PipelineContext) -> PhaseResult:
        """Called once when entering the phase.

        Responsibilities:
        - Send initial prompt to the appropriate agent
        - Initialize phase-specific state fields
        - NOT write state to disk (router handles this)

        Args:
            state: Current state dict (read-only, don't mutate)
            ctx: Pipeline context with files, runtime, agents

        Returns:
            PhaseResult with updates dict and optional next_phase
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

    def _subscribes_to(self, event: WorkflowEvent, handler: Any) -> bool:
        """Check whether a handler has declared interest in this event.

        For tool.* events: match against ToolSpec.tool_names.
        For file.created/file.activity: match path against EventSpec.watch_paths.

        Does NOT evaluate is_ready — that is done in _dispatch().
        Returns False for unknown event kinds.
        """
        # Tool events: match against ToolSpec
        if event.kind.startswith("tool."):
            get_tool_specs = getattr(handler, "get_tool_specs", None)
            if get_tool_specs is None:
                return False
            bare = event.kind[len("tool.") :]
            return any(bare in spec.tool_names for spec in get_tool_specs())

        # File events: match path against EventSpec watch_paths
        if event.kind in ("file.created", "file.activity"):
            get_specs = getattr(handler, "get_event_specs", None)
            if get_specs is None:
                return False
            path = event.path
            if path is None:
                return False
            return any(
                fnmatch.fnmatch(path, pattern)
                for spec in get_specs()
                for pattern in spec.watch_paths
            )

        return False

    def enter_current_phase(self, state: dict, ctx: PipelineContext) -> PhaseResult:
        phase_name = state.get("phase", "")
        handler = self._phases.get(phase_name)
        if handler is None or phase_name in self._entered:
            return PhaseResult({})

        self._entered.add(phase_name)

        result = handler.enter(state, ctx)
        state.update(result.updates)

        from ..sessions.state_store import write_state

        write_state(ctx.files.state, state)

        # If enter() requests an immediate transition, do it
        if result.next_phase is not None:
            return self._transition(state, ctx, phase_name, result.next_phase)

        return result

    def _transition(
        self,
        state: dict,
        ctx: PipelineContext,
        current_phase: str,
        next_phase: str,
    ) -> PhaseResult:
        """Perform a phase transition: update state, write, enter new phase."""
        self._entered.discard(current_phase)
        state["phase"] = next_phase
        state["updated_at"] = self._now_iso()
        state["updated_by"] = "pipeline"
        from ..sessions.state_store import write_state

        write_state(ctx.files.state, state)
        self.enter_current_phase(state, ctx)
        return PhaseResult({})

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
            return {}, None

        # Enter phase once
        if phase_name not in self._entered:
            self.enter_current_phase(state, ctx)

        # Subscription filter: drop unsubscribed events early
        if not self._subscribes_to(event, handler):
            return {}, None

        # Dispatch
        updates, next_phase = self._dispatch(event, handler, state, ctx)

        # Check for exit signal
        exit_code = updates.pop("__exit__", None)
        if exit_code is not None:
            state.update(updates)
            return updates, exit_code

        # Apply updates
        state.update(updates)

        # Phase transition: enter new phase explicitly
        if next_phase is not None:
            self._transition(state, ctx, phase_name, next_phase)
            return {}, None

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
        """Dispatch an event to the handler via its specs.

        Precondition: ``_subscribes_to(event, handler)`` is True.

        Tool-call events (``tool.*``): match against ToolSpec and dispatch
        a ``WorkflowEvent(kind=spec.name, payload=event.payload)``.

        File events (``file.created`` / ``file.activity``): evaluate
        EventSpecs — on path match + is_ready, dispatch a logical event.
        """
        # Route tool.* events via ToolSpec
        if event.kind.startswith("tool."):
            bare_name = event.kind[len("tool.") :]
            for spec in handler.get_tool_specs():
                if bare_name in spec.tool_names:
                    logical = WorkflowEvent(kind=spec.name, payload=event.payload)
                    return handler.handle_event(logical, state, ctx)
            return {}, None

        # Route file events via EventSpec
        if event.kind not in ("file.created", "file.activity"):
            return {}, None

        path = event.path
        if path is None:
            return {}, None

        specs = list(handler.get_event_specs())

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
