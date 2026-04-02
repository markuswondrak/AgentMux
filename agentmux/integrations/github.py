from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from ..shared.models import GitHubConfig


def check_gh_available() -> bool:
    try:
        subprocess.run(["gh", "--version"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def check_gh_authenticated() -> bool:
    try:
        subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, check=True
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


def fetch_issue(issue_ref: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["gh", "issue", "view", issue_ref, "--json", "title,body"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gh CLI is required for --issue. Install: https://cli.github.com"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        raise RuntimeError(
            f"Failed to fetch GitHub issue '{issue_ref}'. Ensure the issue exists and gh is authenticated. {stderr}"
        ) from exc

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse issue payload from gh issue view for '{issue_ref}'."
        ) from exc

    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", ""))
    if not title:
        raise RuntimeError(f"GitHub issue '{issue_ref}' returned an empty title.")
    return {"title": title, "body": body}


def extract_issue_number(issue_ref: str) -> str:
    normalized = issue_ref.strip()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if normalized.isdigit():
        return normalized

    parsed = urlparse(normalized)
    if parsed.scheme and parsed.netloc:
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) >= 2 and segments[-2] == "issues" and segments[-1].isdigit():
            return segments[-1]
        if segments and segments[-1].isdigit():
            return segments[-1]

    raise ValueError(
        f"Invalid issue reference: {issue_ref}. Expected an issue number or GitHub issue URL."
    )


@dataclass(frozen=True)
class IssueBootstrap:
    prompt_text: str
    slug_source: str
    issue_number: str
    gh_available: bool = True


class GitHubBootstrapper:
    def __init__(
        self,
        project_dir: Path,
        github_config: GitHubConfig,
        *,
        output: Callable[[str], None] = print,
    ) -> None:
        self.project_dir = project_dir
        self.github_config = github_config
        self.output = output

    def detect_pr_availability(self) -> bool:
        gh_available = check_gh_available() and check_gh_authenticated()
        if not gh_available:
            self.output(
                "Warning: gh CLI not available or not authenticated. PR creation will be skipped."
            )
        return gh_available

    def resolve_issue(self, issue_ref: str) -> IssueBootstrap:
        if not check_gh_available():
            raise SystemExit(
                "gh CLI is required for --issue. Install: https://cli.github.com"
            )
        if not check_gh_authenticated():
            raise SystemExit("gh is not authenticated. Run: gh auth login")
        try:
            issue_number = extract_issue_number(issue_ref)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        try:
            payload = fetch_issue(issue_ref)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc

        try:
            subprocess.run(
                ["git", "pull", "origin", self.github_config.base_branch],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            self.output(f"Pulled latest from origin/{self.github_config.base_branch}.")
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            self.output(
                f"Warning: could not pull origin/{self.github_config.base_branch}: {stderr}"
            )

        return IssueBootstrap(
            prompt_text=payload["body"].strip() or payload["title"],
            slug_source=payload["title"],
            issue_number=issue_number,
        )


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_first_available(paths: list[Path]) -> str:
    for path in paths:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


def _extract_initial_request(requirements_text: str) -> str:
    match = re.search(
        r"(?ims)^##\s+Initial Request\s*$\n+(.*?)(?=^##\s+|\Z)",
        requirements_text,
    )
    if not match:
        return ""
    return match.group(1).strip()


def _extract_first_plan_section(plan_text: str) -> str:
    heading_match = re.search(r"(?m)^##\s+(.+?)\s*$", plan_text)
    if not heading_match:
        return ""
    section_heading = heading_match.group(1).strip()
    start = heading_match.end()
    rest = plan_text[start:]
    end_match = re.search(r"(?m)^##\s+", rest)
    section_body = rest[: end_match.start()] if end_match else rest
    section_body = section_body.strip()
    if not section_body:
        return section_heading
    return f"{section_heading}\n\n{section_body}"


def _extract_review_verdict(review_text: str) -> str:
    for line in review_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("verdict:"):
            return stripped
    return review_text.strip().splitlines()[0] if review_text.strip() else ""


def assemble_pr_body(feature_dir: Path, issue_number: str | None) -> str:
    requirements_text = _read_text(feature_dir / "requirements.md")
    plan_text = _read_first_available(
        [
            feature_dir / "02_planning" / "plan.md",
        ]
    )
    review_text = _read_first_available(
        [
            feature_dir / "06_review" / "review.md",
        ]
    )

    initial_request = _extract_initial_request(requirements_text) or "(not available)"
    plan_summary = _extract_first_plan_section(plan_text) or "(not available)"
    review_verdict = _extract_review_verdict(review_text) or "(not available)"

    parts = [
        "## Initial Request",
        initial_request,
        "## Plan Summary",
        plan_summary,
        "## Review Verdict",
        review_verdict,
    ]
    if issue_number:
        parts.extend(["", f"Closes #{issue_number}"])
    return "\n\n".join(parts).strip() + "\n"


def create_branch(project_dir: Path, branch_name: str) -> bool:
    """Create a new branch and push it to origin. Returns True on success.

    Handles the case where the branch already exists or we're already on it.
    """
    try:
        # Check if we're already on the target branch
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        if current.stdout.strip() == branch_name:
            # Already on the target branch, just need to push
            subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return True

        # Check if the branch already exists locally
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=False,
        )

        if branch_exists.returncode == 0:
            # Branch exists, checkout to it
            subprocess.run(
                ["git", "checkout", branch_name],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        else:
            # Branch doesn't exist, create it
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )

        # Push to origin
        subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except FileNotFoundError as exc:
        print(f"Branch creation skipped because git was not found: {exc}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        print(f"Branch creation failed: {stderr}")
    return False


def create_branch_and_pr(
    project_dir: Path,
    feature_slug: str,
    github_config: GitHubConfig,
    issue_number: str | None,
    feature_dir: Path,
) -> dict[str, str] | None:
    branch_name = f"{github_config.branch_prefix}{feature_slug}"

    try:
        # If not already on this branch (created at pipeline startup), create it now.
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        if current.stdout.strip() != branch_name:
            if not create_branch(project_dir, branch_name):
                return None
        else:
            subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )

        pr_body = assemble_pr_body(feature_dir, issue_number)
        cmd = [
            "gh",
            "pr",
            "create",
            "--title",
            feature_slug,
            "--body",
            pr_body,
            "--base",
            github_config.base_branch,
            "--head",
            branch_name,
        ]
        if github_config.draft:
            cmd.append("--draft")

        pr_result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )

        pr_output = pr_result.stdout.strip()
        pr_url = pr_output.splitlines()[-1] if pr_output else ""

        try:
            subprocess.run(
                ["git", "checkout", github_config.base_branch],
                cwd=project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            print(
                f"Warning: could not switch back to {github_config.base_branch}: {stderr}"
            )

        return {
            "branch": branch_name,
            "pr_url": pr_url,
        }
    except FileNotFoundError as exc:
        print(f"PR creation skipped because required CLI was not found: {exc}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        cmd_text = (
            " ".join(str(item) for item in exc.cmd)
            if isinstance(exc.cmd, list)
            else str(exc.cmd)
        )
        print(f"PR creation step failed for command `{cmd_text}`: {stderr}")
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"PR creation step failed unexpectedly: {exc}")
    return None
