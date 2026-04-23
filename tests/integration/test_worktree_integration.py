"""Integration tests for WorktreeManager using real git repositories.

These tests exercise WorktreeManager with real subprocess git commands — no mocks
for git operations.  Each test gets a fresh temporary git repository via the
``git_repo`` fixture.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agentmux.integrations.worktree_manager import WorktreeManager
from agentmux.sessions.state_store import STATE_FILE_NAME, load_runtime_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command with a fixed identity so commits never fail."""
    return subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Return a real git repository with one initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    readme = repo / "README.md"
    readme.write_text("# Test repo\n")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "Initial commit"], repo)
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_and_remove_cycle(git_repo: Path) -> None:
    """Create a worktree, verify path + branch exist, remove, verify path gone."""
    manager = WorktreeManager(git_repo)
    worktree_path = manager.compute_worktree_path("my-feature")
    branch = "feature/my-feature"

    result = manager.create(worktree_path, branch)
    assert result.path == worktree_path
    assert result.branch_name == branch
    assert worktree_path.exists()

    listed = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=git_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert branch in listed.stdout

    manager.remove(worktree_path)
    assert not worktree_path.exists()


def test_prune_orphaned_removes_untracked(git_repo: Path, tmp_path: Path) -> None:
    """A subdirectory in worktrees_dir not referenced by any state.json is pruned."""
    worktrees_dir = git_repo.parent / f"{git_repo.name}-worktrees"
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    orphan = worktrees_dir / "orphaned-feature"
    orphan.mkdir()

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()

    pruned = WorktreeManager.prune_orphaned(git_repo, sessions_root)

    assert orphan in pruned
    assert not orphan.exists()


def test_prune_orphaned_keeps_active(git_repo: Path, tmp_path: Path) -> None:
    """A worktree referenced by a live state.json is not pruned."""
    manager = WorktreeManager(git_repo)
    worktree_path = manager.compute_worktree_path("active-feature")
    manager.create(worktree_path, "feature/active-feature")

    sessions_root = tmp_path / "sessions"
    feature_dir = sessions_root / "20240101-000000-active-feature"
    feature_dir.mkdir(parents=True)
    state = {"worktree_path": str(worktree_path), "worktree_enabled": True}
    (feature_dir / STATE_FILE_NAME).write_text(json.dumps(state))

    try:
        pruned = WorktreeManager.prune_orphaned(git_repo, sessions_root)
        assert worktree_path not in pruned
        assert worktree_path.exists()
    finally:
        manager.remove(worktree_path)


def test_recreate_if_missing(git_repo: Path) -> None:
    """Manually deleting the worktree path; recreate_if_missing re-creates it.

    This simulates the real crash scenario: the worktree directory is gone but
    the branch still exists in git (because ``git worktree remove`` was never
    called).  ``recreate_if_missing`` must check out the existing branch without
    ``-b``, which would fail with "branch already exists".
    """
    manager = WorktreeManager(git_repo)
    worktree_path = manager.compute_worktree_path("recreate-me")
    branch = "feature/recreate-me"

    manager.create(worktree_path, branch)
    assert worktree_path.exists()

    # Simulate crash: delete the directory without going through git worktree remove.
    # The branch intentionally remains in git (mirroring a real crash).
    shutil.rmtree(worktree_path)
    # Prune stale git admin entries (worktree path is gone, branch still exists).
    subprocess.run(
        ["git", "worktree", "prune"], cwd=git_repo, check=True, capture_output=True
    )

    assert not worktree_path.exists()
    manager.recreate_if_missing(worktree_path, branch)
    assert worktree_path.exists()

    # Cleanup
    manager.remove(worktree_path)


def test_is_linked_worktree_false_in_main(git_repo: Path) -> None:
    """is_linked_worktree() returns False when called from the main repository."""
    manager = WorktreeManager(git_repo)
    assert manager.is_linked_worktree() is False


def test_is_linked_worktree_true_in_linked(git_repo: Path) -> None:
    """is_linked_worktree(cwd=worktree_path) returns True for a linked worktree."""
    manager = WorktreeManager(git_repo)
    worktree_path = manager.compute_worktree_path("linked-check")
    manager.create(worktree_path, "feature/linked-check")

    try:
        assert manager.is_linked_worktree(cwd=worktree_path) is True
    finally:
        manager.remove(worktree_path)


def test_load_runtime_files_with_real_worktree(git_repo: Path, tmp_path: Path) -> None:
    """load_runtime_files overrides project_dir with worktree_path when
    worktree_enabled."""
    manager = WorktreeManager(git_repo)
    worktree_path = manager.compute_worktree_path("load-runtime-feature")
    manager.create(worktree_path, "feature/load-runtime-feature")

    sessions_root = tmp_path / "sessions"
    feature_dir = sessions_root / "20240101-000000-load-runtime-feature"
    feature_dir.mkdir(parents=True)
    state = {
        "worktree_enabled": True,
        "worktree_path": str(worktree_path),
        "phase": "implementing",
        "feature_dir": str(feature_dir),
        "session_name": "test-session",
    }
    (feature_dir / STATE_FILE_NAME).write_text(json.dumps(state))

    try:
        runtime_files = load_runtime_files(git_repo, feature_dir)
        assert runtime_files.project_dir == worktree_path
    finally:
        manager.remove(worktree_path)
