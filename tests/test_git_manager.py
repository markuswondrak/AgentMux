"""Tests for GitBranchManager resilient branch management."""

import subprocess
from pathlib import Path

from agentmux.integrations.git_manager import BranchState, GitBranchManager


class TestGitBranchManager:
    """Test cases for GitBranchManager."""

    def test_get_current_branch_returns_branch_name(self, tmp_path: Path) -> None:
        """Test getting current branch name."""
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        # Need an initial commit to have a real branch
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        manager = GitBranchManager(tmp_path)

        # Should return main (or master) as default branch
        result = manager.get_current_branch()
        assert result is not None
        assert result in ("main", "master")

    def test_branch_exists_returns_true_for_existing_branch(
        self, tmp_path: Path
    ) -> None:
        """Test checking if branch exists."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        # Create a file and commit so we can create branches
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        manager = GitBranchManager(tmp_path)

        # Create a new branch
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        # Get the default branch name and switch back to it
        default_branch = manager.get_current_branch()
        assert default_branch is not None
        subprocess.run(
            ["git", "checkout", default_branch],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        assert manager.branch_exists("feature/test") is True
        assert manager.branch_exists("feature/nonexistent") is False

    def test_ensure_branch_switches_to_existing_branch(self, tmp_path: Path) -> None:
        """Test ensuring branch switches to existing branch."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        manager = GitBranchManager(tmp_path)
        default_branch = manager.get_current_branch()
        assert default_branch is not None

        # Create feature branch and switch back to default
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", default_branch],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        result = manager.ensure_branch("feature/test")

        assert result.name == "feature/test"
        assert result.created is True
        assert manager.get_current_branch() == "feature/test"

    def test_ensure_branch_creates_new_branch_if_not_exists(
        self, tmp_path: Path
    ) -> None:
        """Test ensuring branch creates new branch if it doesn't exist."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        manager = GitBranchManager(tmp_path)
        result = manager.ensure_branch("feature/new-branch")

        assert result.name == "feature/new-branch"
        assert result.created is True
        assert result.pushed is False
        assert manager.get_current_branch() == "feature/new-branch"

    def test_ensure_branch_noop_if_already_on_branch(self, tmp_path: Path) -> None:
        """Test ensuring branch does nothing if already on correct branch."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        manager = GitBranchManager(tmp_path)
        result = manager.ensure_branch("feature/test")

        assert result.name == "feature/test"
        assert result.created is True  # Already exists
        assert manager.get_current_branch() == "feature/test"

    def test_commit_on_branch_ensures_branch_then_commits(self, tmp_path: Path) -> None:
        """Test that commit_on_branch ensures correct branch before committing."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        manager = GitBranchManager(tmp_path)
        default_branch = manager.get_current_branch()
        assert default_branch is not None

        # Create feature branch and switch back to default
        subprocess.run(
            ["git", "checkout", "-b", "feature/test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "checkout", default_branch],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        # Add a new file
        (tmp_path / "new_file.py").write_text("print('hello')")

        manager = GitBranchManager(tmp_path)

        # Commit should switch to feature branch first, then commit
        commit_hash = manager.commit_on_branch(
            "feature/test", "Test commit message", ["new_file.py"]
        )

        assert commit_hash is not None
        assert len(commit_hash) > 0

        # Verify we're on feature branch
        assert manager.get_current_branch() == "feature/test"

        # Verify the commit is on feature branch, not main
        result = subprocess.run(
            ["git", "log", "feature/test", "--oneline", "-1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Test commit message" in result.stdout

        # Verify main does NOT have this commit
        result_main = subprocess.run(
            ["git", "log", default_branch, "--oneline", "-1"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Test commit message" not in result_main.stdout
        assert "initial" in result_main.stdout

    def test_commit_on_branch_fails_if_would_commit_to_wrong_branch(
        self, tmp_path: Path
    ) -> None:
        """Test that commit_on_branch fails safely if branch verification fails."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        (tmp_path / "test.txt").write_text("test")
        subprocess.run(
            ["git", "add", "test.txt"], cwd=tmp_path, capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )

        (tmp_path / "new_file.py").write_text("print('hello')")

        manager = GitBranchManager(tmp_path)

        # This should work - creates branch and commits
        commit_hash = manager.commit_on_branch(
            "feature/test", "Test commit", ["new_file.py"]
        )

        assert commit_hash is not None


class TestBranchState:
    """Test cases for BranchState dataclass."""

    def test_branch_state_defaults(self) -> None:
        """Test BranchState default values."""
        state = BranchState(name="feature/test")
        assert state.name == "feature/test"
        assert state.created is False
        assert state.pushed is False

    def test_branch_state_explicit_values(self) -> None:
        """Test BranchState with explicit values."""
        state = BranchState(name="feature/test", created=True, pushed=True)
        assert state.name == "feature/test"
        assert state.created is True
        assert state.pushed is True
