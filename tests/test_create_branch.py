"""Tests for create_branch function handling existing branches."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.github import create_branch


class CreateBranchTests(unittest.TestCase):
    """Test cases for the create_branch function."""

    def test_create_branch_returns_true_when_already_on_target_branch(self) -> None:
        """If already on the target branch, should return True without error."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            # Mock: current branch is already the target branch
            with patch(
                "agentmux.integrations.github.subprocess.run",
                side_effect=[
                    # First call: git rev-parse --abbrev-ref HEAD
                    subprocess.CompletedProcess(
                        args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        returncode=0,
                        stdout="feature/test-branch\n",
                        stderr="",
                    ),
                    # Second call: git push -u origin
                    subprocess.CompletedProcess(
                        args=["git", "push", "-u", "origin", "feature/test-branch"],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ],
            ) as run_mock:
                result = create_branch(project_dir, "feature/test-branch")

        self.assertTrue(result)
        # Should only call rev-parse and push, not checkout -b
        self.assertEqual(2, run_mock.call_count)
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(["git", "rev-parse", "--abbrev-ref", "HEAD"], calls[0])
        self.assertEqual(
            ["git", "push", "-u", "origin", "feature/test-branch"], calls[1]
        )

    def test_create_branch_checkouts_existing_branch_when_not_on_it(self) -> None:
        """If branch exists but we're not on it, should checkout to it."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            with patch(
                "agentmux.integrations.github.subprocess.run",
                side_effect=[
                    # First call: git rev-parse --abbrev-ref HEAD (on main)
                    subprocess.CompletedProcess(
                        args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        returncode=0,
                        stdout="main\n",
                        stderr="",
                    ),
                    # Second call: git show-ref --verify (branch exists)
                    subprocess.CompletedProcess(
                        args=[
                            "git",
                            "show-ref",
                            "--verify",
                            "--quiet",
                            "refs/heads/feature/existing",
                        ],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                    # Third call: git checkout (switch to existing branch)
                    subprocess.CompletedProcess(
                        args=["git", "checkout", "feature/existing"],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                    # Fourth call: git push -u origin
                    subprocess.CompletedProcess(
                        args=["git", "push", "-u", "origin", "feature/existing"],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ],
            ) as run_mock:
                result = create_branch(project_dir, "feature/existing")

        self.assertTrue(result)
        self.assertEqual(4, run_mock.call_count)
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(["git", "checkout", "feature/existing"], calls[2])

    def test_create_branch_creates_new_branch_when_not_exists(self) -> None:
        """If branch doesn't exist, should create it with checkout -b."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            with patch(
                "agentmux.integrations.github.subprocess.run",
                side_effect=[
                    # First call: git rev-parse --abbrev-ref HEAD (on main)
                    subprocess.CompletedProcess(
                        args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        returncode=0,
                        stdout="main\n",
                        stderr="",
                    ),
                    # Second call: git show-ref --verify (branch doesn't exist)
                    # Note: check=False, so it returns CompletedProcess with returncode=1
                    subprocess.CompletedProcess(
                        args=[
                            "git",
                            "show-ref",
                            "--verify",
                            "--quiet",
                            "refs/heads/feature/new",
                        ],
                        returncode=1,
                        stdout="",
                        stderr="",
                    ),
                    # Third call: git checkout -b (create new branch)
                    subprocess.CompletedProcess(
                        args=["git", "checkout", "-b", "feature/new"],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                    # Fourth call: git push -u origin
                    subprocess.CompletedProcess(
                        args=["git", "push", "-u", "origin", "feature/new"],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ],
            ) as run_mock:
                result = create_branch(project_dir, "feature/new")

        self.assertTrue(result)
        self.assertEqual(4, run_mock.call_count)
        calls = [call.args[0] for call in run_mock.call_args_list]
        self.assertEqual(["git", "checkout", "-b", "feature/new"], calls[2])

    def test_create_branch_returns_false_on_checkout_failure(self) -> None:
        """If checkout fails, should return False."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            with patch(
                "agentmux.integrations.github.subprocess.run",
                side_effect=[
                    # First call: git rev-parse --abbrev-ref HEAD (on main)
                    subprocess.CompletedProcess(
                        args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        returncode=0,
                        stdout="main\n",
                        stderr="",
                    ),
                    # Second call: git show-ref --verify (branch exists)
                    subprocess.CompletedProcess(
                        args=[
                            "git",
                            "show-ref",
                            "--verify",
                            "--quiet",
                            "refs/heads/feature/broken",
                        ],
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                    # Third call: git checkout (fails)
                    subprocess.CalledProcessError(
                        returncode=1,
                        cmd=["git", "checkout", "feature/broken"],
                        stderr="error: pathspec 'feature/broken' did not match",
                    ),
                ],
            ):
                result = create_branch(project_dir, "feature/broken")

        self.assertFalse(result)

    def test_create_branch_returns_false_on_push_failure(self) -> None:
        """If push fails, should return False."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            with patch(
                "agentmux.integrations.github.subprocess.run",
                side_effect=[
                    # First call: git rev-parse --abbrev-ref HEAD (already on branch)
                    subprocess.CompletedProcess(
                        args=["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        returncode=0,
                        stdout="feature/test\n",
                        stderr="",
                    ),
                    # Second call: git push -u origin (fails)
                    subprocess.CalledProcessError(
                        returncode=1,
                        cmd=["git", "push", "-u", "origin", "feature/test"],
                        stderr="rejected",
                    ),
                ],
            ):
                result = create_branch(project_dir, "feature/test")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
