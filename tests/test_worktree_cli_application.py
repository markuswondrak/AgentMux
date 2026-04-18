"""Tests for --worktree CLI flag and application session preparation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agentmux.integrations.worktree_manager import (
    WorktreeBranchConflictError,
    WorktreeResult,
)
from agentmux.pipeline.application import PipelineApplication
from agentmux.pipeline.cli import build_parser, handle_run
from agentmux.sessions import PreparedSession
from agentmux.sessions.state_store import load_runtime_files, write_state

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_feature_setup(
    project_dir: Path, slug: str = "20240101-120000-my-feature"
) -> tuple[Path, PreparedSession]:
    """Create feature dir, state.json, and PreparedSession."""
    feature_dir = project_dir / ".agentmux" / ".sessions" / slug
    feature_dir.mkdir(parents=True)
    state = {"phase": "architecting", "feature_dir": str(feature_dir)}
    write_state(feature_dir / "state.json", state)
    files = load_runtime_files(project_dir, feature_dir)
    prepared = PreparedSession(
        feature_dir=feature_dir, files=files, product_manager=False
    )
    return feature_dir, prepared


def _make_loaded_config(branch_prefix: str = "feature/") -> MagicMock:
    loaded = MagicMock()
    loaded.session_name = "test-session"
    loaded.github.branch_prefix = branch_prefix
    loaded.agents = {}
    loaded.compression_enabled = False
    return loaded


# ── parser tests ───────────────────────────────────────────────────────────────


class TestWorktreeParserFlag:
    def test_worktree_flag_in_parser(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["run", "--worktree", "some feature"])
        assert args.worktree is True

        args = parser.parse_args(["run", "some feature"])
        assert args.worktree is False


# ── handle_run tests ───────────────────────────────────────────────────────────


class TestHandleRunWorktree:
    def test_handle_run_passes_worktree_true(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--worktree", "my feature"])
        with patch(
            "agentmux.pipeline.application.PipelineApplication.run_prompt",
            return_value=0,
        ) as mock_run:
            handle_run(args, tmp_path)
        mock_run.assert_called_once_with(
            "my feature",
            name=None,
            keep_session=False,
            product_manager=False,
            worktree=True,
        )

    def test_handle_run_passes_worktree_false(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "my feature"])
        with patch(
            "agentmux.pipeline.application.PipelineApplication.run_prompt",
            return_value=0,
        ) as mock_run:
            handle_run(args, tmp_path)
        mock_run.assert_called_once_with(
            "my feature",
            name=None,
            keep_session=False,
            product_manager=False,
            worktree=False,
        )


# ── _prepare_session new-session worktree tests ────────────────────────────────


class TestPrepareSessionNewWorktree:
    def test_prepare_session_new_worktree(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        feature_dir, prepared = _make_feature_setup(project_dir)
        app = PipelineApplication(project_dir)

        loaded = _make_loaded_config()
        args = SimpleNamespace(
            resume=None,
            issue=None,
            prompt="my feature",
            name=None,
            product_manager=False,
            worktree=True,
        )

        expected_slug = "my-feature"
        wt_dir = f"{project_dir.name}-worktrees"
        expected_worktree = project_dir.parent / wt_dir / expected_slug
        expected_branch = "feature/my-feature"

        with (
            patch("agentmux.pipeline.application.GitHubBootstrapper") as mock_gh_cls,
            patch.object(app.sessions, "create", return_value=prepared),
            patch(
                "agentmux.integrations.worktree_manager.WorktreeManager"
            ) as mock_wm_cls,
            patch("agentmux.pipeline.application.GitBranchManager") as mock_git_cls,
        ):
            mock_gh_cls.return_value.detect_pr_availability.return_value = False
            mock_wm = mock_wm_cls.return_value
            mock_wm.compute_worktree_path.return_value = expected_worktree
            mock_wm.create.return_value = WorktreeResult(
                path=expected_worktree, branch_name=expected_branch
            )

            app._prepare_session(args, loaded)

        mock_wm.create.assert_called_once_with(expected_worktree, expected_branch)
        mock_git_cls.return_value.ensure_branch.assert_not_called()

        state = json.loads((feature_dir / "state.json").read_text())
        assert state["worktree_enabled"] is True
        assert state["worktree_path"] == str(expected_worktree)
        assert state["main_repo_dir"] == str(project_dir)
        assert state["feature_branch"] == expected_branch

    def test_prepare_session_no_worktree(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        feature_dir, prepared = _make_feature_setup(project_dir)
        app = PipelineApplication(project_dir)

        loaded = _make_loaded_config()
        args = SimpleNamespace(
            resume=None,
            issue=None,
            prompt="my feature",
            name=None,
            product_manager=False,
            worktree=False,
        )

        with (
            patch("agentmux.pipeline.application.GitHubBootstrapper") as mock_gh_cls,
            patch.object(app.sessions, "create", return_value=prepared),
            patch("agentmux.pipeline.application.GitBranchManager") as mock_git_cls,
        ):
            mock_gh_cls.return_value.detect_pr_availability.return_value = False
            mock_git_cls.return_value.ensure_branch.return_value = MagicMock(
                created=True
            )

            app._prepare_session(args, loaded)

        mock_git_cls.return_value.ensure_branch.assert_called_once_with(
            "feature/my-feature"
        )

    def test_prepare_session_branch_conflict(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        feature_dir, prepared = _make_feature_setup(project_dir)
        app = PipelineApplication(project_dir)

        loaded = _make_loaded_config()
        args = SimpleNamespace(
            resume=None,
            issue=None,
            prompt="my feature",
            name=None,
            product_manager=False,
            worktree=True,
        )

        expected_worktree = (
            project_dir.parent / f"{project_dir.name}-worktrees" / "my-feature"
        )

        with (
            patch("agentmux.pipeline.application.GitHubBootstrapper") as mock_gh_cls,
            patch.object(app.sessions, "create", return_value=prepared),
            patch(
                "agentmux.integrations.worktree_manager.WorktreeManager"
            ) as mock_wm_cls,
            patch("agentmux.pipeline.application.cleanup_feature_dir") as mock_cleanup,
        ):
            mock_gh_cls.return_value.detect_pr_availability.return_value = False
            mock_wm = mock_wm_cls.return_value
            mock_wm.compute_worktree_path.return_value = expected_worktree
            mock_wm.create.side_effect = WorktreeBranchConflictError(
                "feature/my-feature", "/some/other/path"
            )

            with pytest.raises(SystemExit) as exc_info:
                app._prepare_session(args, loaded)

        assert exc_info.value.code == 1
        mock_cleanup.assert_called_once_with(feature_dir)


# ── _run_launcher linked-worktree guard tests ──────────────────────────────────


class TestLinkedWorktreeChecks:
    def _setup(self, tmp_path: Path, worktree: bool):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        app = PipelineApplication(project_dir)
        loaded = _make_loaded_config()
        args = SimpleNamespace(
            resume=None,
            issue=None,
            prompt="my feature",
            name=None,
            product_manager=False,
            worktree=worktree,
            keep_session=False,
            orchestrate=None,
        )
        return app, args, loaded

    def test_prepare_session_linked_worktree_error(self, tmp_path: Path) -> None:
        app, args, loaded = self._setup(tmp_path, worktree=True)

        with (
            patch.object(app, "_mcp_preparer") as mock_mcp,
            patch.object(app, "_check_opencode_model_conflicts", return_value=True),
            patch(
                "agentmux.integrations.worktree_manager.WorktreeManager.prune_orphaned"
            ),
            patch(
                "agentmux.integrations.worktree_manager.WorktreeManager.is_linked_worktree",
                return_value=True,
            ),
        ):
            mock_mcp.return_value.ensure_project_config.return_value = None

            result = app._run_launcher(args, loaded)

        assert result == 1

    def test_prepare_session_linked_worktree_warning(
        self, tmp_path: Path, capsys
    ) -> None:
        app, args, loaded = self._setup(tmp_path, worktree=False)

        with (
            patch.object(app, "_mcp_preparer") as mock_mcp,
            patch.object(app, "_check_opencode_model_conflicts", return_value=True),
            patch(
                "agentmux.integrations.worktree_manager.WorktreeManager.prune_orphaned"
            ),
            patch(
                "agentmux.integrations.worktree_manager.WorktreeManager.is_linked_worktree",
                return_value=True,
            ),
            patch.object(app, "_prepare_session", side_effect=RuntimeError("sentinel")),
        ):
            mock_mcp.return_value.ensure_project_config.return_value = None

            with pytest.raises(RuntimeError, match="sentinel"):
                app._run_launcher(args, loaded)

        captured = capsys.readouterr()
        assert "Warning" in captured.err


# ── _prepare_session resume worktree tests ─────────────────────────────────────


class TestResumeWorktree:
    def test_resume_worktree_enabled(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        main_repo = tmp_path / "main_repo"
        main_repo.mkdir()

        feature_dir = (
            project_dir / ".agentmux" / ".sessions" / "20240101-120000-my-feature"
        )
        feature_dir.mkdir(parents=True)

        worktree_path = tmp_path / "worktrees" / "my-feature"
        state = {
            "phase": "reviewing",
            "feature_branch": "feature/foo",
            "worktree_enabled": True,
            "worktree_path": str(worktree_path),
            "main_repo_dir": str(main_repo),
        }
        write_state(feature_dir / "state.json", state)

        files = load_runtime_files(project_dir, feature_dir)
        prepared = PreparedSession(
            feature_dir=feature_dir, files=files, product_manager=False
        )

        app = PipelineApplication(project_dir)
        loaded = _make_loaded_config()
        args = SimpleNamespace(
            resume=str(feature_dir),
            issue=None,
            prompt=None,
            name=None,
            product_manager=False,
            worktree=False,
        )

        with (
            patch.object(
                app.sessions, "resolve_resume_target", return_value=feature_dir
            ),
            patch.object(
                app.sessions, "prepare_resumed_session", return_value=prepared
            ),
            patch(  # noqa: E501
                "agentmux.integrations.worktree_manager.WorktreeManager"
            ) as mock_wm_cls,
            patch("agentmux.pipeline.application.GitBranchManager") as mock_git_cls,
        ):
            app._prepare_session(args, loaded)

        mock_wm_cls.return_value.recreate_if_missing.assert_called_once_with(
            worktree_path, "feature/foo"
        )
        mock_git_cls.return_value.ensure_branch.assert_not_called()

    def test_resume_worktree_disabled(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        feature_dir = (
            project_dir / ".agentmux" / ".sessions" / "20240101-120000-my-feature"
        )
        feature_dir.mkdir(parents=True)

        state = {
            "phase": "reviewing",
            "feature_branch": "feature/foo",
        }
        write_state(feature_dir / "state.json", state)

        files = load_runtime_files(project_dir, feature_dir)
        prepared = PreparedSession(
            feature_dir=feature_dir, files=files, product_manager=False
        )

        app = PipelineApplication(project_dir)
        loaded = _make_loaded_config()
        args = SimpleNamespace(
            resume=str(feature_dir),
            issue=None,
            prompt=None,
            name=None,
            product_manager=False,
            worktree=False,
        )

        with (
            patch.object(
                app.sessions, "resolve_resume_target", return_value=feature_dir
            ),
            patch.object(
                app.sessions, "prepare_resumed_session", return_value=prepared
            ),
            patch(  # noqa: E501
                "agentmux.integrations.worktree_manager.WorktreeManager"
            ) as mock_wm_cls,
            patch("agentmux.pipeline.application.GitBranchManager") as mock_git_cls,
        ):
            mock_git_cls.return_value.ensure_branch.return_value = MagicMock(
                created=True
            )

            app._prepare_session(args, loaded)

        mock_git_cls.return_value.ensure_branch.assert_called_once_with("feature/foo")
        mock_wm_cls.return_value.recreate_if_missing.assert_not_called()
