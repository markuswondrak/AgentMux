"""Full pipeline integration tests.

These tests exercise PipelineOrchestrator.run() end-to-end with real event
routing, real file-based event sources, and real phase handlers — but a
mocked AgentRuntime (no tmux) and a mocked InterruptionEventSource.

Three scenarios:
  1. Happy path with parallel coders
  2. Happy path with product manager + research tool usage
  3. User closes pane (interruption → exit 130)
"""

from __future__ import annotations

import tempfile
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from agentmux.integrations.completion import CompletionResult
from agentmux.runtime.event_bus import EventBus, SessionEvent
from agentmux.runtime.interruption_sources import (
    INTERRUPTION_EVENT_PANE_EXITED,
    INTERRUPTION_SOURCE_NAME,
)
from agentmux.runtime.tool_events import append_tool_event
from agentmux.sessions.state_store import create_feature_files, load_state
from agentmux.shared.models import (
    AgentConfig,
    CompletionSettings,
    GitHubConfig,
    WorkflowSettings,
)
from agentmux.workflow.orchestrator import PipelineOrchestrator

# ---------------------------------------------------------------------------
# Timeout for all sync waits (seconds). Long enough for CI, short enough to
# fail fast when something is genuinely stuck.
# ---------------------------------------------------------------------------

SYNC_TIMEOUT = 15


# ---------------------------------------------------------------------------
# SyncFakeRuntime — FakeRuntime with threading.Event-based synchronisation
# ---------------------------------------------------------------------------


@dataclass
class _RuntimeCall:
    """A single recorded runtime method call with optional match fields."""

    method: str
    args: tuple[Any, ...]
    event: threading.Event = field(default_factory=threading.Event)


class SyncFakeRuntime:
    """Mock runtime that records calls and allows the test thread to wait for
    specific method invocations from the orchestrator thread.

    Usage from test:
        runtime.wait_for_call("send", match={"role": "architect"})
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: list[_RuntimeCall] = []
        self._any_call_event = threading.Event()

    # -- helpers for tests ---------------------------------------------------

    @property
    def calls(self) -> list[_RuntimeCall]:
        with self._lock:
            return list(self._calls)

    def wait_for_call(
        self,
        method: str,
        *,
        match: dict[str, Any] | None = None,
        timeout: float = SYNC_TIMEOUT,
    ) -> _RuntimeCall:
        """Block until a matching call is recorded. Raises on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                for call in self._calls:
                    if call.method != method:
                        continue
                    if match and not self._matches(call, match):
                        continue
                    return call
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    recorded = [(c.method, c.args) for c in self._calls]
                raise TimeoutError(
                    f"Timed out waiting for {method}(match={match}). "
                    f"Recorded calls: {recorded}"
                )
            self._any_call_event.wait(timeout=min(remaining, 0.2))
            self._any_call_event.clear()

    @staticmethod
    def _matches(call: _RuntimeCall, match: dict[str, Any]) -> bool:
        for key, value in match.items():
            if key == "role":
                if not call.args or call.args[0] != value:
                    return False
            elif key == "min_specs" and (
                len(call.args) < 2 or len(call.args[1]) < value
            ):
                return False
        return True

    # -- recording helper ----------------------------------------------------

    def _record(self, method: str, *args: Any) -> None:
        rc = _RuntimeCall(method=method, args=args)
        with self._lock:
            self._calls.append(rc)
        self._any_call_event.set()

    # -- AgentRuntime protocol implementation --------------------------------

    def send(
        self,
        role: str,
        prompt_file: Path,
        display_label: str | None = None,
        prefix_command: str | None = None,
    ) -> None:
        self._record("send", role, prompt_file, display_label, prefix_command)

    def send_many(self, role: str, prompt_specs: list[object]) -> None:
        self._record("send_many", role, prompt_specs)

    def spawn_task(self, role: str, task_id: str, research_dir: Path) -> None:
        self._record("spawn_task", role, task_id, research_dir)

    def finish_task(self, role: str, task_id: str) -> None:
        self._record("finish_task", role, task_id)

    def hide_task(self, role: str, task_id: int | str) -> None:
        self._record("hide_task", role, task_id)

    def deactivate(self, role: str) -> None:
        self._record("deactivate", role)

    def deactivate_many(self, roles: Iterable[str]) -> None:
        self._record("deactivate_many", tuple(roles))

    def finish_many(self, role: str) -> None:
        self._record("finish_many", role)

    def kill_primary(self, role: str) -> None:
        self._record("kill_primary", role)

    def notify(self, role: str, text: str) -> None:
        self._record("notify", role, text)

    def shutdown(self, keep_session: bool) -> None:
        self._record("shutdown", keep_session)

    def show_completion_ui(self, feature_dir: Path) -> None:
        self._record("show_completion_ui", feature_dir)


# ---------------------------------------------------------------------------
# NoOpEventSource / TriggerableInterruptionSource
# ---------------------------------------------------------------------------


class NoOpEventSource:
    """EventSource that does nothing — replaces InterruptionEventSource."""

    def start(self, bus: EventBus) -> None:
        pass

    def stop(self) -> None:
        pass


class TriggerableInterruptionSource:
    """Manually triggerable interruption source for the pane-exit test."""

    def __init__(self) -> None:
        self._bus: EventBus | None = None
        self._started = threading.Event()

    def start(self, bus: EventBus) -> None:
        self._bus = bus
        self._started.set()

    def stop(self) -> None:
        self._bus = None

    def trigger(
        self, *, role: str, message: str, timeout: float = SYNC_TIMEOUT
    ) -> None:
        if not self._started.wait(timeout=timeout):
            raise TimeoutError("Interruption source was never started")
        assert self._bus is not None
        self._bus.publish(
            SessionEvent(
                kind=INTERRUPTION_EVENT_PANE_EXITED,
                source=INTERRUPTION_SOURCE_NAME,
                payload={
                    "interruption_type": "pane_exited",
                    "role": role,
                    "pane_scope": "primary",
                    "task_id": None,
                    "pane_id": "%0",
                    "label": role,
                    "message": message,
                },
            )
        )


# ---------------------------------------------------------------------------
# _InstrumentedOrchestrator — overrides build_event_bus to inject
# controllable interruption source and expose tool-event flushing
# ---------------------------------------------------------------------------


class _InstrumentedOrchestrator(PipelineOrchestrator):
    """Subclass that replaces InterruptionEventSource with an injectable source
    and exposes a ``flush_tool_events()`` method so tests do not depend on
    watchdog inotify timing (which is inherently racy in fast tests).
    """

    def __init__(
        self,
        interruption_source: (
            NoOpEventSource | TriggerableInterruptionSource | None
        ) = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._interruption_source = interruption_source or NoOpEventSource()
        self._tool_source: Any = None
        self._tool_bus: EventBus | None = None

    def build_event_bus(self, files, runtime, wake_event: threading.Event) -> EventBus:
        from agentmux.runtime.event_bus import build_wake_listener
        from agentmux.runtime.file_events import (
            CreatedFilesLogListener,
            FileEventSource,
        )
        from agentmux.runtime.tool_events import ToolCallEventSource

        self._tool_source = ToolCallEventSource(files.feature_dir)
        bus = EventBus(
            sources=[
                FileEventSource(files.feature_dir),
                self._tool_source,
                self._interruption_source,
            ]
        )
        self._tool_bus = bus
        bus.register(build_wake_listener(wake_event))
        bus.register(CreatedFilesLogListener(files.created_files_log).handle_event)
        return bus

    def flush_tool_events(self) -> None:
        """Force the ToolCallEventSource to read and emit any pending entries.

        Call this after ``_emit_tool()`` to guarantee the event is processed
        without waiting for watchdog inotify delivery.
        """
        if self._tool_source is not None and self._tool_bus is not None:
            self._tool_source._on_modified(self._tool_bus)

    def flush_file_event(self, feature_dir: Path, relative_path: str) -> None:
        """Publish a file-created + file-activity event directly on the bus.

        Bypasses watchdog inotify so the test doesn't depend on timing.
        """
        from agentmux.runtime.file_events import publish_file_event

        if self._tool_bus is not None:
            publish_file_event(self._tool_bus, "created", relative_path)
            publish_file_event(self._tool_bus, "activity", relative_path)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_agents(*, with_pm: bool = False) -> dict[str, AgentConfig]:
    agents: dict[str, AgentConfig] = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "planner": AgentConfig(role="planner", cli="claude", model="opus", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
        "reviewer_logic": AgentConfig(
            role="reviewer_logic", cli="claude", model="sonnet", args=[]
        ),
    }
    if with_pm:
        agents["product-manager"] = AgentConfig(
            role="product-manager", cli="claude", model="opus", args=[]
        )
    return agents


def _tool_events_path(feature_dir: Path) -> Path:
    return feature_dir / "tool_events.jsonl"


def _emit_tool(
    feature_dir: Path,
    tool_name: str,
    payload: dict | None = None,
    *,
    orchestrator: _InstrumentedOrchestrator | None = None,
) -> None:
    """Append a tool event and optionally flush the event source.

    When *orchestrator* is provided, ``flush_tool_events()`` is called to
    guarantee immediate processing instead of relying on watchdog timing.
    """
    append_tool_event(_tool_events_path(feature_dir), tool_name, payload or {})
    if orchestrator is not None:
        orchestrator.flush_tool_events()


def _write_architecture(feature_dir: Path) -> None:
    d = feature_dir / "02_architecting"
    d.mkdir(parents=True, exist_ok=True)
    (d / "architecture.md").write_text(
        "# Architecture\n\nSimple layered architecture.\n", encoding="utf-8"
    )


def _write_plan_yaml(feature_dir: Path, *, parallel: bool = True) -> None:
    d = feature_dir / "04_planning"
    d.mkdir(parents=True, exist_ok=True)
    mode = "parallel" if parallel else "serial"
    plan_data = {
        "version": 2,
        "plan_overview": "Two-phase implementation",
        "groups": [
            {
                "group_id": "g1",
                "mode": mode,
                "plans": [
                    {"index": 1, "name": "Feature A", "file": "plan_1.md"},
                    {"index": 2, "name": "Feature B", "file": "plan_2.md"},
                ],
            }
        ],
        "subplans": [
            {
                "index": 1,
                "title": "Feature A",
                "scope": "Implement feature A",
                "owned_files": ["src/a.py"],
                "dependencies": "None",
                "implementation_approach": "Write feature A",
                "acceptance_criteria": "Tests pass",
                "tasks": ["Implement A", "Test A"],
            },
            {
                "index": 2,
                "title": "Feature B",
                "scope": "Implement feature B",
                "owned_files": ["src/b.py"],
                "dependencies": "None",
                "implementation_approach": "Write feature B",
                "acceptance_criteria": "Tests pass",
                "tasks": ["Implement B", "Test B"],
            },
        ],
        "review_strategy": {"severity": "medium", "focus": []},
        "needs_design": False,
        "needs_docs": False,
        "doc_files": [],
    }
    (d / "plan.yaml").write_text(yaml.safe_dump(plan_data), encoding="utf-8")


def _write_review_pass(feature_dir: Path) -> None:
    d = feature_dir / "07_review"
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "verdict": "pass",
        "summary": "All checks pass, implementation is solid.",
        "findings": [],
        "commit_message": "feat: implement feature",
    }
    (d / "review.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _write_summary(
    feature_dir: Path,
    *,
    orchestrator: _InstrumentedOrchestrator | None = None,
) -> None:
    d = feature_dir / "08_completion"
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.md").write_text(
        "## Summary\nImplemented the feature successfully.\n", encoding="utf-8"
    )
    if orchestrator is not None:
        orchestrator.flush_file_event(feature_dir, "08_completion/summary.md")


def _wait_and_flush_approval(
    feature_dir: Path,
    orchestrator: _InstrumentedOrchestrator,
) -> None:
    """Wait for approval.json to appear (written by CompletingHandler) and
    flush the corresponding file event to avoid watchdog timing issues."""
    approval = feature_dir / "08_completion" / "approval.json"
    deadline = time.monotonic() + SYNC_TIMEOUT
    while not approval.exists():
        if time.monotonic() > deadline:
            raise TimeoutError("approval.json never appeared")
        time.sleep(0.05)
    orchestrator.flush_file_event(feature_dir, "08_completion/approval.json")


def _run_in_background(
    orchestrator: _InstrumentedOrchestrator,
    ctx: Any,
    keep_session: bool = True,
) -> tuple[threading.Thread, list[int]]:
    """Start orchestrator.run() in a daemon thread.

    Returns (thread, exit_codes) where exit_codes is a shared list that the
    thread appends to on completion.
    """
    exit_codes: list[int] = []

    def _target() -> None:
        code = orchestrator.run(ctx, keep_session)
        exit_codes.append(code)

    t = threading.Thread(target=_target, daemon=True, name="test-orchestrator")
    t.start()
    return t, exit_codes


# ---------------------------------------------------------------------------
# Patches applied to all pipeline tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def _pipeline_patches():
    """Mock CompletionService and _git_status_porcelain to avoid git operations."""
    mock_result = CompletionResult(
        commit_hash="abc123",
        pr_url=None,
        cleaned_up=True,
        should_cleanup=False,
    )
    with (
        patch("agentmux.workflow.handlers.completing.COMPLETION_SERVICE") as mock_cs,
        patch(
            "agentmux.workflow.handlers.completing._git_status_porcelain",
            return_value="",
        ),
    ):
        mock_cs.finalize_approval.return_value = mock_result
        mock_cs.resolve_commit_message.return_value = "feat: test"
        yield mock_cs


# ---------------------------------------------------------------------------
# Test 1: Happy path — parallel coders
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_pipeline_patches")
def test_happy_path_parallel_coders():
    """Full pipeline: architecting → planning → implementing (2 parallel) →
    reviewing (pass + summary) → completing (auto-approve) → exit 0."""
    with tempfile.TemporaryDirectory() as td:
        project_dir = Path(td) / "project"
        project_dir.mkdir()
        feature_dir = Path(td) / "feature"

        files = create_feature_files(
            project_dir, feature_dir, "integration test", "sess-1"
        )
        runtime = SyncFakeRuntime()
        orchestrator = _InstrumentedOrchestrator()
        ctx = orchestrator.create_context(
            files=files,
            runtime=runtime,
            agents=_make_agents(),
            max_review_iterations=3,
            github_config=GitHubConfig(),
            workflow_settings=WorkflowSettings(
                completion=CompletionSettings(skip_final_approval=True)
            ),
        )

        thread, exit_codes = _run_in_background(orchestrator, ctx)
        try:
            # Phase 1: architecting — wait for architect prompt
            runtime.wait_for_call("send", match={"role": "architect"})

            # Simulate architect output
            _write_architecture(feature_dir)
            _emit_tool(feature_dir, "submit_architecture", orchestrator=orchestrator)

            # Phase 2: planning — wait for planner prompt
            runtime.wait_for_call("send", match={"role": "planner"})

            # Simulate planner output
            _write_plan_yaml(feature_dir, parallel=True)
            _emit_tool(feature_dir, "submit_plan", orchestrator=orchestrator)

            # Phase 3: implementing — wait for parallel dispatch
            runtime.wait_for_call("send_many", match={"role": "coder"})

            # Verify send_many was called with 2 specs
            send_many_call = runtime.wait_for_call(
                "send_many", match={"role": "coder", "min_specs": 2}
            )
            assert len(send_many_call.args[1]) == 2

            # Simulate both coders finishing
            _emit_tool(
                feature_dir,
                "submit_done",
                {"subplan_index": 1},
                orchestrator=orchestrator,
            )
            _emit_tool(
                feature_dir,
                "submit_done",
                {"subplan_index": 2},
                orchestrator=orchestrator,
            )

            # Phase 4: reviewing — wait for reviewer prompt
            runtime.wait_for_call("send", match={"role": "reviewer_logic"})

            # Simulate review pass
            _write_review_pass(feature_dir)
            _emit_tool(feature_dir, "submit_review", orchestrator=orchestrator)

            # Wait for summary prompt to reviewer
            # After review pass, the handler sends a summary prompt to the
            # same reviewer — this is the second "send" to reviewer_logic
            calls_before = len(
                [
                    c
                    for c in runtime.calls
                    if c.method == "send" and c.args[0] == "reviewer_logic"
                ]
            )
            if calls_before < 2:
                # Wait for the summary prompt
                deadline = time.monotonic() + SYNC_TIMEOUT
                while True:
                    reviewer_sends = [
                        c
                        for c in runtime.calls
                        if c.method == "send" and c.args[0] == "reviewer_logic"
                    ]
                    if len(reviewer_sends) >= 2:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Timed out waiting for summary prompt")
                    time.sleep(0.1)

            # Simulate summary written
            _write_summary(feature_dir, orchestrator=orchestrator)

            # Phase 5: completing — auto-approval (skip_final_approval=True)
            # CompletingHandler.enter() writes approval.json; we may need to
            # nudge the file event so the watchdog doesn't swallow it.
            _wait_and_flush_approval(feature_dir, orchestrator)

            # The orchestrator should exit with code 0
            thread.join(timeout=SYNC_TIMEOUT)
            assert not thread.is_alive(), "Orchestrator did not exit"
            assert exit_codes == [0], f"Expected exit 0, got {exit_codes}"

            # Verify state ended at a terminal state
            state = load_state(files.state)
            assert (
                state.get("cleanup_feature_dir") is not None
                or state.get("phase") is not None
            )

        finally:
            if thread.is_alive():
                # Force exit in case of test failure
                if orchestrator._exit_event:
                    orchestrator._exit_event.set()
                thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test 2: Happy path — PM with research
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_pipeline_patches")
def test_happy_path_pm_with_research():
    """Full pipeline starting from product_management with code research
    dispatch/done, then normal flow through to completion."""
    with tempfile.TemporaryDirectory() as td:
        project_dir = Path(td) / "project"
        project_dir.mkdir()
        feature_dir = Path(td) / "feature"

        files = create_feature_files(
            project_dir,
            feature_dir,
            "PM research test",
            "sess-2",
            product_manager=True,
        )
        runtime = SyncFakeRuntime()
        orchestrator = _InstrumentedOrchestrator()
        ctx = orchestrator.create_context(
            files=files,
            runtime=runtime,
            agents=_make_agents(with_pm=True),
            max_review_iterations=3,
            github_config=GitHubConfig(),
            workflow_settings=WorkflowSettings(
                completion=CompletionSettings(skip_final_approval=True)
            ),
        )

        thread, exit_codes = _run_in_background(orchestrator, ctx)
        try:
            # Phase 0: product_management — wait for PM prompt
            runtime.wait_for_call("send", match={"role": "product-manager"})

            # PM dispatches code research
            _emit_tool(
                feature_dir,
                "research_dispatch_code",
                {
                    "topic": "auth",
                    "context": "Need to understand authentication flow",
                    "questions": ["How does the auth module work?"],
                    "scope_hints": ["src/auth/"],
                },
                orchestrator=orchestrator,
            )

            # Wait for spawn_task (research dispatched)
            runtime.wait_for_call("spawn_task", match={"role": "code-researcher"})

            # Research completes
            _emit_tool(
                feature_dir,
                "submit_research_done",
                {"topic": "auth", "type": "code"},
                orchestrator=orchestrator,
            )

            # Wait for PM notification about research completion
            runtime.wait_for_call("notify", match={"role": "product-manager"})

            # PM signals done
            _emit_tool(feature_dir, "submit_pm_done", orchestrator=orchestrator)

            # Phase 1: architecting
            runtime.wait_for_call("send", match={"role": "architect"})
            _write_architecture(feature_dir)
            _emit_tool(feature_dir, "submit_architecture", orchestrator=orchestrator)

            # Phase 2: planning
            runtime.wait_for_call("send", match={"role": "planner"})
            _write_plan_yaml(feature_dir, parallel=True)
            _emit_tool(feature_dir, "submit_plan", orchestrator=orchestrator)

            # Phase 3: implementing (parallel)
            runtime.wait_for_call("send_many", match={"role": "coder"})
            _emit_tool(
                feature_dir,
                "submit_done",
                {"subplan_index": 1},
                orchestrator=orchestrator,
            )
            _emit_tool(
                feature_dir,
                "submit_done",
                {"subplan_index": 2},
                orchestrator=orchestrator,
            )

            # Phase 4: reviewing
            runtime.wait_for_call("send", match={"role": "reviewer_logic"})
            _write_review_pass(feature_dir)
            _emit_tool(feature_dir, "submit_review", orchestrator=orchestrator)

            # Wait for second reviewer_logic send (summary prompt)
            deadline = time.monotonic() + SYNC_TIMEOUT
            while True:
                reviewer_sends = [
                    c
                    for c in runtime.calls
                    if c.method == "send" and c.args[0] == "reviewer_logic"
                ]
                if len(reviewer_sends) >= 2:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Timed out waiting for summary prompt")
                time.sleep(0.1)

            _write_summary(feature_dir, orchestrator=orchestrator)
            _wait_and_flush_approval(feature_dir, orchestrator)

            # Phase 5: completing
            thread.join(timeout=SYNC_TIMEOUT)
            assert not thread.is_alive(), "Orchestrator did not exit"
            assert exit_codes == [0], f"Expected exit 0, got {exit_codes}"

            # Verify research was tracked
            spawn_calls = [c for c in runtime.calls if c.method == "spawn_task"]
            assert any(
                c.args[0] == "code-researcher" and c.args[1] == "auth"
                for c in spawn_calls
            ), f"Expected spawn_task for code-researcher/auth, got {spawn_calls}"

            notify_calls = [c for c in runtime.calls if c.method == "notify"]
            assert any(c.args[0] == "product-manager" for c in notify_calls), (
                f"Expected notify to product-manager, got {notify_calls}"
            )

        finally:
            if thread.is_alive():
                if orchestrator._exit_event:
                    orchestrator._exit_event.set()
                thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Test 3: User closes pane (interruption)
# ---------------------------------------------------------------------------


def test_user_closes_pane():
    """Architecting → user closes pane → exit 130, state=failed."""
    with tempfile.TemporaryDirectory() as td:
        project_dir = Path(td) / "project"
        project_dir.mkdir()
        feature_dir = Path(td) / "feature"

        files = create_feature_files(
            project_dir, feature_dir, "interruption test", "sess-3"
        )
        runtime = SyncFakeRuntime()
        interruption_source = TriggerableInterruptionSource()
        orchestrator = _InstrumentedOrchestrator(
            interruption_source=interruption_source,
        )
        ctx = orchestrator.create_context(
            files=files,
            runtime=runtime,
            agents=_make_agents(),
            max_review_iterations=3,
            github_config=GitHubConfig(),
        )

        thread, exit_codes = _run_in_background(orchestrator, ctx)
        try:
            # Wait for architect prompt — confirms phase is entered
            runtime.wait_for_call("send", match={"role": "architect"})

            # Simulate user closing the architect pane
            interruption_source.trigger(
                role="architect",
                message="Agent pane architect was closed or exited.",
            )

            # Orchestrator should exit
            thread.join(timeout=SYNC_TIMEOUT)
            assert not thread.is_alive(), "Orchestrator did not exit after interruption"
            assert exit_codes == [130], f"Expected exit 130, got {exit_codes}"

            # Verify state
            state = load_state(files.state)
            assert state["phase"] == "failed"
            assert state.get("interruption_category") == "canceled"
            assert state.get("interruption_cause") is not None

        finally:
            if thread.is_alive():
                if orchestrator._exit_event:
                    orchestrator._exit_event.set()
                thread.join(timeout=5)
