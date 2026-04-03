"""Resilient git branch management for the pipeline.

This module provides centralized branch management to ensure commits always
happen on the correct feature branch, preventing accidental commits to main.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BranchState:
    """State of a git branch operation.

    Attributes:
        name: The branch name
        created: Whether the branch was created (or already existed)
        pushed: Whether the branch has been pushed to origin
    """

    name: str
    created: bool = False
    pushed: bool = False


class GitBranchManager:
    """Manages git branch operations for the pipeline.

    Ensures that all commits happen on the correct feature branch by:
    1. Tracking the expected branch name
    2. Verifying/switching to the correct branch before operations
    3. Creating branches when needed
    4. Pushing branches after commits

    Usage:
        manager = GitBranchManager(project_dir)

        # At startup - ensure branch exists
        branch_state = manager.ensure_branch("feature/my-feature")

        # During completion - commit on correct branch
        commit_hash = manager.commit_on_branch(
            "feature/my-feature",
            "commit message",
            ["file1.py", "file2.py"]
        )
    """

    def __init__(self, project_dir: Path) -> None:
        """Initialize the branch manager.

        Args:
            project_dir: Path to the git repository root
        """
        self.project_dir = project_dir

    def get_current_branch(self) -> str | None:
        """Get the current git branch name.

        Returns:
            The name of the current branch, or None if not in a git repo
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            # Defensive: handle case where subprocess.run returns None (mocked in tests)
            if result is None:
                return None
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def branch_exists(self, branch_name: str) -> bool:
        """Check if a branch exists locally.

        Args:
            branch_name: Name of the branch to check

        Returns:
            True if the branch exists locally, False otherwise
        """
        result = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def ensure_branch(self, branch_name: str) -> BranchState:
        """Ensure we're on the specified branch, creating it if needed.

        This is the core method that prevents commits to the wrong branch.
        It will:
        1. Check current branch
        2. If already on target branch, return success
        3. If branch exists locally, switch to it
        4. If branch doesn't exist, create it from current HEAD

        Args:
            branch_name: The target branch name

        Returns:
            BranchState indicating the result of the operation

        Raises:
            subprocess.CalledProcessError: If git commands fail
        """
        current = self.get_current_branch()

        if current is None:
            # Not in a git repo - can't manage branches
            print(
                f"Warning: Not in a git repository, cannot ensure branch {branch_name}"
            )
            return BranchState(name=branch_name, created=False)

        if current == branch_name:
            # Already on the correct branch
            return BranchState(name=branch_name, created=True)

        if self.branch_exists(branch_name):
            # Branch exists, switch to it
            subprocess.run(
                ["git", "checkout", branch_name],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return BranchState(name=branch_name, created=True)
        else:
            # Branch doesn't exist, create it
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return BranchState(name=branch_name, created=True, pushed=False)

    def push_branch(self, branch_name: str) -> bool:
        """Push branch to origin with upstream tracking.

        Args:
            branch_name: Name of the branch to push

        Returns:
            True if push succeeded, False otherwise
        """
        try:
            subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            print(f"Warning: failed to push branch {branch_name}: {stderr}")
            return False

    def commit_on_branch(
        self,
        branch_name: str,
        commit_message: str,
        commit_files: list[str],
    ) -> str | None:
        """Ensure correct branch, stage files, and commit.

        This is the safe commit method that guarantees commits happen on
        the specified branch. It will:
        1. Switch to the target branch (creating if needed)
        2. Stage the specified files
        3. Create the commit
        4. Return the commit hash

        Args:
            branch_name: The target branch for the commit
            commit_message: The commit message
            commit_files: List of file paths to commit (relative to project_dir)

        Returns:
            The commit hash if successful, None if commit failed
        """
        # Step 1: Ensure we're on the correct branch
        branch_state = self.ensure_branch(branch_name)
        if not branch_state.created:
            print(f"Warning: Could not ensure branch {branch_name}, skipping commit")
            return None

        # Step 2: Stage files
        files = [path.strip() for path in commit_files if path and path.strip()]
        if not files:
            print("Warning: commit_files is empty; skipping commit.")
            return None

        try:
            add_result = subprocess.run(
                ["git", "add", *files],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            if add_result.stderr.strip():
                print(f"Warning: git add stderr: {add_result.stderr.strip()}")
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            print(f"Warning: failed to stage commit files: {stderr}")
            return None

        # Step 3: Create commit
        if not commit_message.strip():
            print("Warning: commit_message is empty; skipping commit.")
            return None

        try:
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            if commit_result.stderr.strip():
                print(f"Warning: git commit stderr: {commit_result.stderr.strip()}")
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            print(f"Warning: failed to create commit: {stderr}")
            return None

        # Step 4: Get commit hash
        try:
            rev_parse = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            print(f"Warning: commit created but failed to read commit hash: {stderr}")
            return None

        commit_hash = rev_parse.stdout.strip()
        if not commit_hash:
            print("Warning: commit created but rev-parse returned an empty hash.")
            return None

        return commit_hash
