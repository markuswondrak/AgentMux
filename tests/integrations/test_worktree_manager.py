"""Tests for WorktreeManager git worktree integration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agentmux.integrations.worktree_manager import (
    WorktreeBranchConflictError,
    WorktreeManager,
    WorktreeResult,
)


class TestComputeWorktreePath:
    def test_compute_worktree_path(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "my-repo"
        manager = WorktreeManager(repo_dir)
        result = manager.compute_worktree_path("my-feature")
        assert result == tmp_path / "my-repo-worktrees" / "my-feature"


class TestIsLinkedWorktree:
    def test_is_linked_worktree_main(self, tmp_path: Path) -> None:
        """Returns False when git-common-dir == '.git' (main repo)."""
        manager = WorktreeManager(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ".git\n"
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = manager.is_linked_worktree(tmp_path)
        mock_run.assert_called_once()
        assert result is False

    def test_is_linked_worktree_linked(self, tmp_path: Path) -> None:
        """Returns True when git-common-dir is an absolute path (linked worktree)."""
        manager = WorktreeManager(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/home/user/repo/.git\n"
        with patch("subprocess.run", return_value=mock_result):
            result = manager.is_linked_worktree(tmp_path)
        assert result is True

    def test_is_linked_worktree_not_git_repo(self, tmp_path: Path) -> None:
        """Returns False when git exits non-zero (directory is not a git repo)."""
        manager = WorktreeManager(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            result = manager.is_linked_worktree(tmp_path)
        assert result is False


class TestCreate:
    def test_create_success(self, tmp_path: Path) -> None:
        """Successful worktree creation returns WorktreeResult."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "repo-worktrees" / "feature-x"
        branch_name = "feature/feature-x"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = manager.create(worktree_path, branch_name)

        assert isinstance(result, WorktreeResult)
        assert result.path == worktree_path
        assert result.branch_name == branch_name
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "worktree" in args
        assert "add" in args
        assert "-b" in args
        assert branch_name in args

    def test_create_branch_conflict(self, tmp_path: Path) -> None:
        """Raises WorktreeBranchConflictError when branch already checked out."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "repo-worktrees" / "feature-x"
        branch_name = "feature/feature-x"
        conflicting = "/home/user/repo-worktrees/other"

        exc = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "worktree", "add"],
            stderr=f"fatal: '{branch_name}' is already checked out at '{conflicting}'",
        )
        with (
            patch("subprocess.run", side_effect=exc),
            pytest.raises(WorktreeBranchConflictError) as exc_info,
        ):
            manager.create(worktree_path, branch_name)

        err = exc_info.value
        assert err.branch_name == branch_name
        assert err.conflicting_path == conflicting

    def test_create_path_already_exists(self, tmp_path: Path) -> None:
        """Raises RuntimeError on generic git worktree add failure."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "repo-worktrees" / "feature-x"
        branch_name = "feature/feature-x"

        exc = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "worktree", "add"],
            stderr="fatal: '/some/path' already exists",
        )
        with patch("subprocess.run", side_effect=exc), pytest.raises(RuntimeError):
            manager.create(worktree_path, branch_name)


class TestRemove:
    def test_remove_success(self, tmp_path: Path) -> None:
        """Calls git worktree remove --force when path exists."""
        repo_dir = tmp_path / "repo"
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "wt"
        worktree_path.mkdir()

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            manager.remove(worktree_path)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "worktree" in args
        assert "remove" in args
        assert "--force" in args
        assert str(worktree_path) in args

    def test_remove_noop_missing(self, tmp_path: Path) -> None:
        """Does not call subprocess when path does not exist."""
        repo_dir = tmp_path / "repo"
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "nonexistent"

        with patch("subprocess.run") as mock_run:
            manager.remove(worktree_path)

        mock_run.assert_not_called()


class TestRecreateIfMissing:
    def test_recreate_if_missing_creates(self, tmp_path: Path) -> None:
        """Prunes stale entries then adds existing branch without -b."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "wt-missing"
        branch_name = "feature/foo"

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            manager.recreate_if_missing(worktree_path, branch_name)

        assert mock_run.call_count == 2
        # First call: git worktree prune
        prune_cmd = mock_run.call_args_list[0][0][0]
        assert "worktree" in prune_cmd
        assert "prune" in prune_cmd
        # Second call: git worktree add <path> <branch> — no -b flag
        add_cmd = mock_run.call_args_list[1][0][0]
        assert "worktree" in add_cmd
        assert "add" in add_cmd
        assert "-b" not in add_cmd
        assert str(worktree_path) in add_cmd
        assert branch_name in add_cmd

    def test_recreate_if_missing_noop(self, tmp_path: Path) -> None:
        """Does not call subprocess when worktree_path exists."""
        repo_dir = tmp_path / "repo"
        manager = WorktreeManager(repo_dir)
        worktree_path = tmp_path / "wt-existing"
        worktree_path.mkdir()
        branch_name = "feature/foo"

        with patch("subprocess.run") as mock_run:
            manager.recreate_if_missing(worktree_path, branch_name)

        mock_run.assert_not_called()


class TestPruneOrphaned:
    def test_prune_orphaned(self, tmp_path: Path) -> None:
        """Removes orphan worktrees not referenced by any active session."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        sessions_root = tmp_path / "sessions"
        sessions_root.mkdir()

        worktrees_dir = tmp_path / "repo-worktrees"
        worktrees_dir.mkdir()

        # Active worktree (referenced by a session)
        active_wt = worktrees_dir / "active-feature"
        active_wt.mkdir()

        # Orphan worktree (not referenced)
        orphan_wt = worktrees_dir / "orphan-feature"
        orphan_wt.mkdir()

        # Create a session with state.json pointing to active_wt
        session_dir = sessions_root / "active-session"
        session_dir.mkdir()
        state = {"phase": "implementing", "worktree_path": str(active_wt)}
        (session_dir / "state.json").write_text(json.dumps(state))

        # git worktree list --porcelain output (only shows active)
        porcelain_output = (
            f"worktree {active_wt}\nHEAD abc123\nbranch refs/heads/feature/active\n\n"
        )

        def fake_run(cmd, *args, **kwargs):
            if "list" in cmd and "--porcelain" in cmd:
                m = MagicMock()
                m.stdout = porcelain_output
                return m
            return MagicMock()

        with patch("subprocess.run", side_effect=fake_run), patch("shutil.rmtree"):
            pruned = WorktreeManager.prune_orphaned(repo_dir, sessions_root)

        assert orphan_wt in pruned
        assert active_wt not in pruned

    def test_prune_orphaned_empty(self, tmp_path: Path) -> None:
        """Returns [] and does nothing when worktrees dir does not exist."""
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        sessions_root = tmp_path / "sessions"
        sessions_root.mkdir()

        with patch("subprocess.run") as mock_run:
            # prune call is still allowed
            mock_run.return_value = MagicMock()
            pruned = WorktreeManager.prune_orphaned(repo_dir, sessions_root)

        assert pruned == []
