"""Tests for worktree-aware load_runtime_files in state_store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmux.sessions.state_store import load_runtime_files


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir


@pytest.fixture()
def tmp_feature(tmp_path: Path) -> Path:
    feature_dir = tmp_path / "feature"
    feature_dir.mkdir()
    return feature_dir


def test_load_runtime_files_no_worktree(tmp_project: Path, tmp_feature: Path) -> None:
    """No state.json → project_dir unchanged."""
    result = load_runtime_files(tmp_project, tmp_feature)
    assert result.project_dir == tmp_project


def test_load_runtime_files_worktree_active(
    tmp_path: Path, tmp_project: Path, tmp_feature: Path
) -> None:
    """worktree_enabled=True and existing path → project_dir becomes worktree_path."""
    worktree_dir = tmp_path / "worktree"
    worktree_dir.mkdir()
    state = {"worktree_enabled": True, "worktree_path": str(worktree_dir)}
    (tmp_feature / "state.json").write_text(json.dumps(state), encoding="utf-8")

    result = load_runtime_files(tmp_project, tmp_feature)
    assert result.project_dir == worktree_dir


def test_load_runtime_files_worktree_path_missing(
    tmp_project: Path, tmp_feature: Path
) -> None:
    """worktree_enabled=True but path doesn't exist → falls back to project_dir."""
    state = {
        "worktree_enabled": True,
        "worktree_path": "/nonexistent/worktree/path/abc123",
    }
    (tmp_feature / "state.json").write_text(json.dumps(state), encoding="utf-8")

    result = load_runtime_files(tmp_project, tmp_feature)
    assert result.project_dir == tmp_project


def test_load_runtime_files_worktree_enabled_false(
    tmp_path: Path, tmp_project: Path, tmp_feature: Path
) -> None:
    """worktree_enabled=False → project_dir unchanged even if path exists."""
    worktree_dir = tmp_path / "worktree"
    worktree_dir.mkdir()
    state = {"worktree_enabled": False, "worktree_path": str(worktree_dir)}
    (tmp_feature / "state.json").write_text(json.dumps(state), encoding="utf-8")

    result = load_runtime_files(tmp_project, tmp_feature)
    assert result.project_dir == tmp_project


def test_load_runtime_files_suppresses_exceptions(
    tmp_project: Path, tmp_feature: Path
) -> None:
    """Invalid JSON in state.json → no exception, project_dir unchanged."""
    (tmp_feature / "state.json").write_text("not valid json {{{", encoding="utf-8")

    result = load_runtime_files(tmp_project, tmp_feature)
    assert result.project_dir == tmp_project
