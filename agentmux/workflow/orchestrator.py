from __future__ import annotations

import threading

from ..integrations.mcp import cleanup_mcp
from ..runtime.event_bus import EventBus, SessionEvent, build_wake_listener
from ..runtime.file_events import CreatedFilesLogListener, FileEventSource
from ..runtime.interruption_sources import INTERRUPTION_EVENT_PANE_EXITED, InterruptionEventSource
from ..sessions.state_store import load_state
from ..shared.models import GitHubConfig, WorkflowSettings
from .interruptions import InterruptionService
from .prompts import build_initial_prompts
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext
from .phases import run_phase_cycle


class PipelineOrchestrator:
    def __init__(self, interruptions: InterruptionService | None = None) -> None:
        self.interruptions = interruptions or InterruptionService()

    def create_context(
        self,
        files,
        runtime,
        agents,
        max_review_iterations: int,
        github_config: GitHubConfig,
        workflow_settings: WorkflowSettings | None = None,
    ) -> PipelineContext:
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
        bus = EventBus(
            sources=[
                FileEventSource(files.feature_dir),
                InterruptionEventSource(runtime),
            ]
        )
        bus.register(build_wake_listener(wake_event))
        bus.register(CreatedFilesLogListener(files.created_files_log).handle_event)
        return bus

    def run(self, ctx: PipelineContext, keep_session: bool) -> int:
        wake_event = threading.Event()
        event_bus = self.build_event_bus(ctx.files, ctx.runtime, wake_event)
        pending_interruption: dict[str, object] | None = None
        interruption_lock = threading.Lock()

        def _handle_interruption(event: SessionEvent) -> None:
            nonlocal pending_interruption
            if event.kind != INTERRUPTION_EVENT_PANE_EXITED:
                return
            with interruption_lock:
                if pending_interruption is None:
                    pending_interruption = dict(event.payload)
            wake_event.set()

        event_bus.register(_handle_interruption)
        event_bus.start()

        try:
            while True:
                wake_event.wait(timeout=1.0)
                wake_event.clear()
                with interruption_lock:
                    interruption = pending_interruption
                if interruption is not None:
                    report = self.interruptions.build_canceled(
                        ctx.files.feature_dir,
                        str(interruption.get("message", "")).strip() or "An agent pane exited unexpectedly.",
                        files=ctx.files,
                    )
                    self.interruptions.persist(ctx.files, report)
                    return 130

                state = load_state(ctx.files.state)
                result = run_phase_cycle(state, ctx)
                if result == EXIT_SUCCESS:
                    return 0
                if result == EXIT_FAILURE:
                    return 1
        finally:
            try:
                event_bus.stop()
            finally:
                try:
                    cleanup_mcp(ctx.files.feature_dir, ctx.files.project_dir)
                finally:
                    ctx.runtime.shutdown(keep_session)
