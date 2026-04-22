"""Git worktree management for AgentMux parallel agent sessions."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorktreeResult:
    path: Path
    branch_name: str


class WorktreeBranchConflictError(Exception):
    def __init__(self, branch_name: str, conflicting_path: str) -> None:
        super().__init__(
            f"Branch '{branch_name}' is already checked out at '{conflicting_path}'"
        )
        self.branch_name = branch_name
        self.conflicting_path = conflicting_path


class WorktreeManager:
    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir

    def is_linked_worktree(self, cwd: Path | None = None) -> bool:
        """Return True if cwd (or repo_dir) is a linked worktree (not main)."""
        check_dir = cwd if cwd is not None else self.repo_dir
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-common-dir"],
                cwd=check_dir,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0 and result.stdout.strip() != ".git"
        except Exception:
            return False

    def compute_worktree_path(self, feature_slug: str) -> Path:
        """Return <repo_dir.parent>/<repo_dir.name>-worktrees/<feature_slug>."""
        return self.repo_dir.parent / f"{self.repo_dir.name}-worktrees" / feature_slug

    def _check_worktree_branch(self, worktree_path: Path) -> str | None:
        """Return the branch checked out at worktree_path, or None on failure."""
        try:
            result = subprocess.run(
                ["git", "-C", str(worktree_path), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def create(self, worktree_path: Path, branch_name: str) -> WorktreeResult:
        """Create a git worktree at worktree_path on branch branch_name.

        Handles pre-existing worktrees/branches gracefully:
        - If worktree_path already exists on the correct branch, reuses it.
        - If the branch already exists, retries without ``-b``.
        """
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # Pre-check: reuse existing worktree if path is already on correct branch
        if worktree_path.exists():
            actual_branch = self._check_worktree_branch(worktree_path)
            if actual_branch == branch_name:
                logger.info("Reusing existing worktree at %s", worktree_path)
                return WorktreeResult(path=worktree_path, branch_name=branch_name)
            raise RuntimeError(
                f"Worktree path '{worktree_path}' already exists on different "
                f"branch '{actual_branch}' (expected '{branch_name}')"
            )

        try:
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            if "already checked out" in stderr:
                # Parse: fatal: 'branch' is already checked out at '/path'
                matches = re.findall(r"'([^']+)'", stderr)
                conflicting_path = matches[-1] if len(matches) >= 2 else ""
                raise WorktreeBranchConflictError(
                    branch_name, conflicting_path
                ) from exc
            if "already exists" in stderr:
                # Branch exists but isn't checked out elsewhere; attach it.
                return self._add_existing_branch(worktree_path, branch_name)
            raise RuntimeError(f"git worktree add failed: {stderr.strip()}") from exc
        return WorktreeResult(path=worktree_path, branch_name=branch_name)

    def _add_existing_branch(
        self, worktree_path: Path, branch_name: str
    ) -> WorktreeResult:
        """Add a worktree for a branch that already exists (no -b flag)."""
        try:
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch_name],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"git worktree add failed: {(exc.stderr or '').strip()}"
            ) from exc
        return WorktreeResult(path=worktree_path, branch_name=branch_name)

    def remove(self, worktree_path: Path) -> None:
        """Remove the worktree at worktree_path; no-op if path does not exist."""
        if not worktree_path.exists():
            return
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            logger.warning("Failed to remove worktree %s: %s", worktree_path, stderr)

    def recreate_if_missing(self, worktree_path: Path, branch_name: str) -> None:
        """Create worktree if it does not already exist."""
        if worktree_path.exists():
            return
        # The branch likely already exists from the original session.
        # Prune stale admin entries, then check out the existing branch without -b.
        subprocess.run(
            ["git", "worktree", "prune"], cwd=self.repo_dir, capture_output=True
        )
        try:
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch_name],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"git worktree add failed: {exc.stderr.strip()}"
            ) from exc

    @staticmethod
    def prune_orphaned(repo_dir: Path, sessions_root: Path) -> list[Path]:
        """Prune orphaned worktrees not referenced by any active session."""
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=repo_dir,
            capture_output=True,
        )

        worktrees_dir = repo_dir.parent / f"{repo_dir.name}-worktrees"
        if not worktrees_dir.exists():
            return []

        # Collect active worktree paths from session state files
        active_paths: set[Path] = set()
        if sessions_root.exists():
            for state_file in sessions_root.rglob("state.json"):
                try:
                    state = json.loads(state_file.read_text())
                    if wt_path := state.get("worktree_path"):
                        active_paths.add(Path(wt_path))
                except Exception:
                    pass

        pruned: list[Path] = []
        for candidate in worktrees_dir.iterdir():
            if not candidate.is_dir():
                continue
            if candidate in active_paths:
                continue
            try:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(candidate)],
                    cwd=repo_dir,
                    capture_output=True,
                    check=True,
                )
            except Exception:
                if candidate.is_symlink():
                    candidate.unlink(missing_ok=True)
                else:
                    logger.warning(
                        "git worktree remove failed for %s; "
                        "falling back to shutil.rmtree",
                        candidate,
                    )
                    shutil.rmtree(candidate, ignore_errors=True)
            print(f"Pruned orphaned worktree: {candidate}")
            pruned.append(candidate)

        return pruned
