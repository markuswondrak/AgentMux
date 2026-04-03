from __future__ import annotations

import threading
from contextlib import ExitStack

from ..integrations.compression import cleanup_compression
from ..integrations.mcp import cleanup_mcp
from ..runtime.event_bus import EventBus, SessionEvent, build_wake_listener
from ..runtime.file_events import CreatedFilesLogListener, FileEventSource
from ..runtime.interruption_sources import (
    INTERRUPTION_EVENT_PANE_EXITED,
    InterruptionEventSource,
)
from ..sessions.state_store import cleanup_feature_dir, load_state
from ..shared.models import BATCH_AGENT_ROLES, GitHubConfig, WorkflowSettings
from .event_router import WorkflowEvent, WorkflowEventRouter
from .handlers import PHASE_HANDLERS
from .interruptions import InterruptionService
from .prompts import build_initial_prompts
from .transitions import PipelineContext


class PipelineOrchestrator:
    """Event-driven pipeline orchestrator.

    Replaces the polling loop with an event-driven callback pattern.
    Uses WorkflowEventRouter to route events to phase-specific handlers.
    """

    def __init__(self, interruptions: InterruptionService | None = None) -> None:
        self.interruptions = interruptions or InterruptionService()
        self._router = WorkflowEventRouter(PHASE_HANDLERS)
        self._exit_code: int | None = None
        self._exit_event: threading.Event | None = None
        self._ctx: PipelineContext | None = None

    def create_context(
        self,
        files,
        runtime,
        agents,
        max_review_iterations: int,
        github_config: GitHubConfig,
        workflow_settings: WorkflowSettings | None = None,
    ) -> PipelineContext:
        """Create a pipeline context with initial prompts."""
        return PipelineContext(
            files=files,
            runtime=runtime,
            agents=agents,
            max_review_iterations=max_review_iterations,
            prompts=build_initial_prompts(files),
            github_config=github_config,
            workflow_settings=workflow_settings or WorkflowSettings(),
        )

    def build_event_bus(self, files, runtime, wake_event: threading.Event) -> EventBus:
        """Build the event bus with file and interruption sources."""
        bus = EventBus(
            sources=[
                FileEventSource(files.feature_dir),
                InterruptionEventSource(runtime),
            ]
        )
        bus.register(build_wake_listener(wake_event))
        bus.register(CreatedFilesLogListener(files.created_files_log).handle_event)
        return bus

    def _normalize_event(self, event: SessionEvent) -> WorkflowEvent:
        """Convert SessionEvent to WorkflowEvent.

        File events get their relative_path extracted to the path field.
        Interruption events keep their full payload.
        """
        if event.kind.startswith("file."):
            return WorkflowEvent(
                kind=event.kind,
                path=event.payload.get("relative_path"),
                payload=event.payload,
            )
        return WorkflowEvent(
            kind=event.kind,
            path=None,
            payload=event.payload,
        )

    def _handle_interruption(self, event: WorkflowEvent, ctx: PipelineContext) -> None:
        """Handle pane exit interruption.

        Notifies the appropriate agent if a researcher subagent crashed,
        persists the interruption report, and sets the exit code.
        """
        payload = event.payload
        role = str(payload.get("role", ""))
        task_id = payload.get("task_id")
        pane_scope = str(payload.get("pane_scope", ""))

        # Check if this is a researcher subagent that crashed
        if role in BATCH_AGENT_ROLES and task_id and pane_scope == "parallel":
            state = load_state(ctx.files.state)
            owner = self._determine_research_owner(state, role)

            if owner:
                message = str(payload.get("message", "Task failed")).strip()
                ctx.runtime.notify(
                    owner,
                    f"RESEARCH TASK FAILED: {role} task '{task_id}' "
                    "crashed unexpectedly.\n"
                    f"Error: {message}\n"
                    "You may need to retry this research task or proceed without it.",
                )

        report = self.interruptions.build_canceled(
            ctx.files.feature_dir,
            str(payload.get("message", "")).strip()
            or "An agent pane exited unexpectedly.",
            files=ctx.files,
        )
        self.interruptions.persist(ctx.files, report)
        self._exit_code = 130
        if self._exit_event:
            self._exit_event.set()

    def _determine_research_owner(self, state: dict, role: str) -> str | None:
        """Determine which agent owns a research task based on current phase.

        During product_management phase, the product-manager owns the research.
        During architecting/planning/implementing phases, the architect owns
        the research.
        """
        phase = state.get("phase", "")
        if phase == "product_management":
            return "product-manager"
        elif phase in ("architecting", "planning", "implementing"):
            return "architect"
        return None

    def _on_event(self, event: SessionEvent) -> None:
        """Event callback - routes events to handlers.

        This is the main entry point for all events. It normalizes the event,
        handles interruptions specially, and routes other events to the
        appropriate phase handler via the router.
        """
        if self._exit_code is not None:
            return  # Already exiting

        if self._ctx is None:
            return  # Not initialized

        # Convert to workflow event
        wf_event = self._normalize_event(event)

        # Handle interruption specially
        if wf_event.kind == INTERRUPTION_EVENT_PANE_EXITED:
            self._handle_interruption(wf_event, self._ctx)
            return

        # Route to phase handler
        state = load_state(self._ctx.files.state)
        updates, exit_code = self._router.handle(wf_event, state, self._ctx)

        if exit_code is not None:
            self._exit_code = exit_code
            if self._exit_event:
                self._exit_event.set()

    def run(self, ctx: PipelineContext, keep_session: bool) -> int:
        """Run the pipeline - event-driven, no loop.

        Uses ExitStack to ensure cleanup happens in correct LIFO order:
        bus.stop → cleanup_mcp → cleanup_compression → shutdown → cleanup_feature_dir
        """
        self._ctx = ctx
        self._exit_code = None
        self._exit_event = threading.Event()

        # Build event bus with our callback
        wake_event = threading.Event()
        bus = self.build_event_bus(ctx.files, ctx.runtime, wake_event)
        bus.register(self._on_event)
        bus.start()

        def handle_feature_dir_cleanup():
            """Clean up feature dir if flagged in state and not keeping session."""
            if keep_session:
                return  # Don't delete feature dir if keeping session
            state = load_state(ctx.files.state)
            if state.get("cleanup_feature_dir"):
                cleanup_feature_dir(ctx.files.feature_dir)

        with ExitStack() as stack:
            # Register callbacks in REVERSE order of desired execution (LIFO)
            # Order: bus.stop, cleanup_mcp, cleanup_compression, shutdown, cleanup_dir
            stack.callback(handle_feature_dir_cleanup)
            stack.callback(ctx.runtime.shutdown, keep_session)
            stack.callback(cleanup_compression, ctx.files.feature_dir)
            stack.callback(cleanup_mcp, ctx.files.feature_dir, ctx.files.project_dir)
            stack.callback(bus.stop)

            # Block until exit signal (no loop!)
            self._exit_event.wait()
            return self._exit_code or 0
