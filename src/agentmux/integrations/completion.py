from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..sessions.state_store import (
    feature_slug_from_dir,
)
from ..shared.models import GitHubConfig, RuntimeFiles
from .git_manager import GitBranchManager
from .github import (
    _extract_first_plan_section,
    _extract_initial_request,
    create_pr_only,
)


@dataclass(frozen=True)
class CompletionResult:
    commit_hash: str | None
    pr_url: str | None
    cleaned_up: bool
    should_cleanup: bool = False


class CompletionService:
    def draft_commit_message(
        self, *, files: RuntimeFiles, issue_number: str | None
    ) -> str:
        initial_request = _extract_initial_request(_read_text(files.requirements))
        summary = _summary_line(initial_request)
        if not summary:
            plan_section = _extract_first_plan_section(_read_text(files.plan))
            summary = _summary_line(plan_section)
        if not summary:
            summary = feature_slug_from_dir(files.feature_dir).replace("-", " ").strip()
        if not summary:
            summary = "update implementation"
        summary = summary.rstrip(".")

        suffix = f" (#{issue_number})" if issue_number else ""
        prefix = "feat: "
        max_summary_len = max(10, 72 - len(prefix) - len(suffix))
        if len(summary) > max_summary_len:
            summary = f"{summary[: max_summary_len - 3].rstrip()}..."
        return f"{prefix}{summary}{suffix}"

    def resolve_commit_message(
        self,
        *,
        payload_commit_message: object,
        files: RuntimeFiles,
        issue_number: str | None,
    ) -> str:
        if isinstance(payload_commit_message, str):
            stripped = payload_commit_message.strip()
            if stripped:
                return stripped
        return self.draft_commit_message(files=files, issue_number=issue_number)

    def finalize_approval(
        self,
        *,
        files: RuntimeFiles,
        github_config: GitHubConfig,
        gh_available: bool,
        issue_number: str | None,
        commit_message: str,
        changed_paths: list[str],
    ) -> CompletionResult:
        """Finalize approval by committing to feature branch and creating PR.

        Uses GitBranchManager to ensure commits always happen on the correct
        feature branch, preventing accidental commits to main.
        """
        # Use GitBranchManager to ensure we're on the correct branch before committing
        git_manager = GitBranchManager(files.project_dir)
        branch_name = (
            f"{github_config.branch_prefix}{feature_slug_from_dir(files.feature_dir)}"
        )

        # Ensure branch exists and we're on it BEFORE committing
        git_manager.ensure_branch(branch_name)

        # Now commit - guaranteed to be on feature branch
        commit_hash = git_manager.commit_on_branch(
            branch_name, commit_message, changed_paths
        )
        if commit_hash is None:
            return CompletionResult(commit_hash=None, pr_url=None, cleaned_up=False)

        # Push the branch immediately after commit
        git_manager.push_branch(branch_name)

        pr_url: str | None = None
        if gh_available:
            # Use simplified PR creation (no branch switching)
            result = create_pr_only(
                project_dir=files.project_dir,
                branch_name=branch_name,
                feature_slug=feature_slug_from_dir(files.feature_dir),
                github_config=github_config,
                issue_number=issue_number,
                feature_dir=files.feature_dir,
            )
            if result:
                pr_url = result["pr_url"]

        return CompletionResult(
            commit_hash=commit_hash,
            pr_url=pr_url,
            cleaned_up=False,
            should_cleanup=True,
        )


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _summary_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
