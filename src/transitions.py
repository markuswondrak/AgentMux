from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import AgentConfig, RuntimeFiles


EXIT_SUCCESS = "EXIT_SUCCESS"
EXIT_FAILURE = "EXIT_FAILURE"


@dataclass
class PipelineContext:
    """Mutable bag of state passed to all transition handlers."""

    files: RuntimeFiles
    panes: dict[str, str | None]
    coder_panes: dict[int, str]
    agents: dict[str, AgentConfig]
    max_review_iterations: int
    session_name: str
    # Startup prompt paths (architect is prebuilt; others may be written lazily).
    prompts: dict[str, Path]
    handled: set[str] = field(default_factory=set)


@dataclass
class Transition:
    """A single state machine transition."""

    source: str
    guard: Callable[[dict[str, Any], PipelineContext], bool]
    action: Callable[[dict[str, Any], PipelineContext], str | None]
    description: str = ""


def not_handled(state: dict[str, Any], ctx: PipelineContext) -> bool:
    return state["status"] not in ctx.handled


def dispatch(
    state: dict[str, Any],
    transitions: list[Transition],
    ctx: PipelineContext,
) -> str | None:
    """Find the first matching transition and execute it. Returns the action result."""
    status = state.get("status")
    for t in transitions:
        if t.source == status and t.guard(state, ctx):
            return t.action(state, ctx)
    return None
