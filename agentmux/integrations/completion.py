from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..sessions.state_store import (
    cleanup_feature_dir,
    commit_changes,
    feature_slug_from_dir,
)
from ..shared.models import GitHubConfig, RuntimeFiles
from .github import _extract_first_plan_section, _extract_initial_request, create_branch_and_pr


@dataclass(frozen=True)
class CompletionResult:
    commit_hash: str | None
    pr_url: str | None
    cleaned_up: bool


class CompletionService:
    def draft_commit_message(self, *, files: RuntimeFiles, issue_number: str | None) -> str:
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
        commit_hash = commit_changes(files.project_dir, commit_message, changed_paths)
        if commit_hash is None:
            return CompletionResult(commit_hash=None, pr_url=None, cleaned_up=False)

        pr_url: str | None = None
        if gh_available:
            result = create_branch_and_pr(
                project_dir=files.project_dir,
                feature_slug=feature_slug_from_dir(files.feature_dir),
                github_config=github_config,
                issue_number=issue_number,
                feature_dir=files.feature_dir,
            )
            if result:
                pr_url = result["pr_url"]

        cleanup_feature_dir(files.feature_dir)
        return CompletionResult(commit_hash=commit_hash, pr_url=pr_url, cleaned_up=True)


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
