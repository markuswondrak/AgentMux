"""Event-driven workflow router infrastructure.

This module provides the core infrastructure for the event-driven orchestrator
refactor. It defines the event types, handler protocol, and router that
routes events to phase-specific handlers.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .transitions import PipelineContext


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


@runtime_checkable
class PhaseHandler(Protocol):
    """Protocol for phase-specific event handling.

    Each phase (planning, implementing, etc.) implements this protocol.
    The router calls enter() once per phase, then handle_event() for each event.
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

    def handle_event(
        self, event: WorkflowEvent, state: dict, ctx: PipelineContext
    ) -> tuple[dict, str | None]:
        """Handle an event for this phase.

        Responsibilities:
        - Check if event is relevant (path matching, content parsing)
        - Perform actions (notify agents, dispatch tasks, etc.)
        - NOT write state to disk (router handles this)

        Args:
            event: The workflow event to process
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

        # Handle the event
        updates, next_phase = handler.handle_event(event, state, ctx)

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

    @staticmethod
    def _now_iso() -> str:
        """Get current timestamp in ISO format."""
        return datetime.now().astimezone().isoformat(timespec="seconds")

    # Keep static methods for backward compatibility within the class
    path_matches = staticmethod(path_matches)
    path_matches_any = staticmethod(path_matches_any)


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
