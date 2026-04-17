"""Tests for worktree cleanup in PipelineOrchestrator and main_repo_dir in
CompletingHandler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.workflow.orchestrator import PipelineOrchestrator
from agentmux.workflow.transitions import PipelineContext

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _FakeRuntime:
    def __init__(self) -> None:
        self.parallel_panes: dict[str, Any] = {}
        self._process_pids: dict[str, int] = {}
        self._shutdown_called = False

    def notify(self, role: str, message: str) -> None:  # noqa: ARG002
        pass

    def spawn_task(self, role: str, task_id: str, research_dir: Path) -> None:  # noqa: ARG002
        self.parallel_panes.setdefault(role, {})[task_id] = f"%{role}-{task_id}"

    def finish_task(self, role: str, task_id: str) -> None:  # noqa: ARG002
        pass

    def shutdown(self, keep_session: bool) -> None:  # noqa: ARG002
        self._shutdown_called = True


class _MockEventBus:
    def register(self, listener: Any) -> None:  # noqa: ARG002
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _make_ctx(
    tmp_path: Path,
    state_extra: dict | None = None,
) -> tuple[PipelineContext, PipelineOrchestrator]:
    """Create a minimal PipelineContext for orchestrator run() tests."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    feature_dir = tmp_path / "feature"

    files = create_feature_files(project_dir, feature_dir, "test-feature", "sess-x")

    # Patch state with completing phase + any extras
    state = load_state(files.state)
    state["phase"] = "completing"
    if state_extra:
        state.update(state_extra)
    write_state(files.state, state)

    runtime = _FakeRuntime()
    ctx = PipelineContext(
        files=files,
        runtime=runtime,
        agents={},
        max_review_iterations=3,
        prompts={},
    )
    orchestrator = PipelineOrchestrator()
    return ctx, orchestrator


def _run_with_immediate_exit(
    orchestrator: PipelineOrchestrator,
    ctx: PipelineContext,
    keep_session: bool = False,
) -> int:
    """Run the orchestrator, signalling immediate exit from enter_current_phase."""
    mock_bus = _MockEventBus()

    def _immediate_exit(state: dict, ctx_inner: Any) -> None:  # noqa: ARG001
        orchestrator._exit_code = 0
        if orchestrator._exit_event:
            orchestrator._exit_event.set()

    with (
        patch.object(orchestrator, "build_event_bus", return_value=mock_bus),
        patch.object(
            orchestrator._router,
            "enter_current_phase",
            side_effect=_immediate_exit,
        ),
        patch("agentmux.workflow.orchestrator.cleanup_compression"),
        patch("agentmux.workflow.orchestrator.cleanup_mcp"),
    ):
        return orchestrator.run(ctx, keep_session=keep_session)


# ---------------------------------------------------------------------------
# Test 1: ExitStack registers worktree cleanup when worktree_enabled=True
# ---------------------------------------------------------------------------


def test_orchestrator_exitstack_registers_worktree_cleanup(tmp_path: Path) -> None:
    """WorktreeManager.remove is called with worktree_path when worktree_enabled."""
    worktree_path = tmp_path / "worktrees" / "my-feature"
    worktree_path.mkdir(parents=True)

    ctx, orchestrator = _make_ctx(
        tmp_path,
        state_extra={
            "worktree_enabled": True,
            "worktree_path": str(worktree_path),
            "main_repo_dir": str(tmp_path / "project"),
        },
    )

    with patch("agentmux.workflow.orchestrator.WorktreeManager") as mock_wm_cls:
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm

        _run_with_immediate_exit(orchestrator, ctx, keep_session=False)

    mock_wm.remove.assert_called_once_with(worktree_path)


# ---------------------------------------------------------------------------
# Test 2: No worktree cleanup when worktree_enabled is absent/False
# ---------------------------------------------------------------------------


def test_orchestrator_exitstack_no_worktree(tmp_path: Path) -> None:
    """WorktreeManager.remove is NOT called when worktree_enabled is not set."""
    ctx, orchestrator = _make_ctx(tmp_path, state_extra={})

    with patch("agentmux.workflow.orchestrator.WorktreeManager") as mock_wm_cls:
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm

        _run_with_immediate_exit(orchestrator, ctx, keep_session=False)

    mock_wm.remove.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: Worktree cleanup suppressed when keep_session=True
# ---------------------------------------------------------------------------


def test_orchestrator_worktree_cleanup_suppressed_on_keep_session(
    tmp_path: Path,
) -> None:
    """WorktreeManager.remove is NOT called when keep_session=True."""
    worktree_path = tmp_path / "worktrees" / "my-feature"
    worktree_path.mkdir(parents=True)

    ctx, orchestrator = _make_ctx(
        tmp_path,
        state_extra={
            "worktree_enabled": True,
            "worktree_path": str(worktree_path),
            "main_repo_dir": str(tmp_path / "project"),
        },
    )

    with patch("agentmux.workflow.orchestrator.WorktreeManager") as mock_wm_cls:
        mock_wm = MagicMock()
        mock_wm_cls.return_value = mock_wm

        _run_with_immediate_exit(orchestrator, ctx, keep_session=True)

    mock_wm.remove.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: _handle_approval uses main_repo_dir for ProjectPaths.from_project
# ---------------------------------------------------------------------------


def test_completing_last_completion_uses_main_repo_dir(tmp_path: Path) -> None:
    """ProjectPaths.from_project is called with Path(state['main_repo_dir'])."""
    from agentmux.workflow.handlers.completing import CompletingHandler

    main_repo = tmp_path / "main_repo"
    main_repo.mkdir()

    # Build a mock context
    ctx = MagicMock()
    completion_dir = tmp_path / "08_completion"
    completion_dir.mkdir()
    ctx.files.completion_dir = completion_dir
    ctx.files.project_dir = tmp_path / "worktree"  # different from main_repo
    ctx.files.feature_dir = tmp_path / "feature"
    ctx.github_config.branch_prefix = "feature/"

    # Write approval.json
    approval_path = completion_dir / "approval.json"
    approval_path.write_text(
        json.dumps({"action": "approve", "commit_message": "feat: done"}),
        encoding="utf-8",
    )

    state = {"main_repo_dir": str(main_repo)}

    mock_result = MagicMock()
    mock_result.commit_hash = "abc123"
    mock_result.pr_url = None
    mock_result.should_cleanup = True

    mock_paths = MagicMock()
    mock_paths.last_completion = tmp_path / ".last_completion.json"
    mock_paths.last_completion.parent.mkdir(parents=True, exist_ok=True)

    handler = CompletingHandler()

    with (
        patch(
            "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
            return_value=mock_result,
        ),
        patch(
            "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.resolve_commit_message",
            return_value="feat: done",
        ),
        patch(
            "agentmux.workflow.handlers.completing._git_status_porcelain",
            return_value="",
        ),
        patch(
            "agentmux.workflow.handlers.completing.ProjectPaths.from_project",
            return_value=mock_paths,
        ) as mock_from_project,
    ):
        handler._handle_approval(state, ctx)

    mock_from_project.assert_called_once_with(Path(str(main_repo)))


# ---------------------------------------------------------------------------
# Test 5: _handle_approval falls back to ctx.files.project_dir when no main_repo_dir
# ---------------------------------------------------------------------------


def test_completing_last_completion_fallback_no_main_repo_dir(tmp_path: Path) -> None:
    """ProjectPaths.from_project falls back to ctx.files.project_dir."""
    from agentmux.workflow.handlers.completing import CompletingHandler

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    ctx = MagicMock()
    completion_dir = tmp_path / "08_completion"
    completion_dir.mkdir()
    ctx.files.completion_dir = completion_dir
    ctx.files.project_dir = project_dir
    ctx.files.feature_dir = tmp_path / "feature"
    ctx.github_config.branch_prefix = "feature/"

    approval_path = completion_dir / "approval.json"
    approval_path.write_text(
        json.dumps({"action": "approve", "commit_message": "feat: done"}),
        encoding="utf-8",
    )

    # state has NO main_repo_dir
    state: dict = {}

    mock_result = MagicMock()
    mock_result.commit_hash = "abc123"
    mock_result.pr_url = None
    mock_result.should_cleanup = True

    mock_paths = MagicMock()
    mock_paths.last_completion = tmp_path / ".last_completion.json"
    mock_paths.last_completion.parent.mkdir(parents=True, exist_ok=True)

    handler = CompletingHandler()

    with (
        patch(
            "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
            return_value=mock_result,
        ),
        patch(
            "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.resolve_commit_message",
            return_value="feat: done",
        ),
        patch(
            "agentmux.workflow.handlers.completing._git_status_porcelain",
            return_value="",
        ),
        patch(
            "agentmux.workflow.handlers.completing.ProjectPaths.from_project",
            return_value=mock_paths,
        ) as mock_from_project,
    ):
        handler._handle_approval(state, ctx)

    mock_from_project.assert_called_once_with(project_dir)
