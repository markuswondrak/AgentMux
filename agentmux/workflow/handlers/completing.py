"""Event-driven handler for completing phase."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from agentmux.workflow.event_router import PhaseHandler, WorkflowEvent
from agentmux.workflow.phase_helpers import (
    apply_role_preferences,
    filter_file_created_event,
    send_to_role,
)
from agentmux.workflow.prompts import build_confirmation_prompt, write_prompt_file
from agentmux.agent_labels import role_display_label
from agentmux.integrations.completion import CompletionService
from agentmux.sessions.state_store import feature_slug_from_dir
from agentmux.shared.models import ProjectPaths

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


COMPLETION_SERVICE = CompletionService()


def _git_status_porcelain(project_dir: Path) -> str:
    """Get git status in porcelain format."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        print(f"Warning: failed to read git status for commit selection: {stderr}")
        return ""


def _parse_changed_paths(status_output: str) -> list[str]:
    """Parse changed paths from git status output."""
    paths: list[str] = []
    for raw_line in status_output.splitlines():
        if not raw_line.strip():
            continue
        entry = raw_line[3:] if len(raw_line) >= 4 else raw_line
        path = entry.split(" -> ", maxsplit=1)[-1].strip()
        if path:
            paths.append(path)
    return paths


class CompletingHandler:
    """Event-driven handler for completing phase."""

    def enter(self, state: dict, ctx: "PipelineContext") -> dict:
        """Called when entering completing phase.

        Sends confirmation prompt or auto-approves if configured.
        """
        approval_path = ctx.files.completion_dir / "approval.json"
        if approval_path.exists():
            approval_path.unlink()

        if ctx.workflow_settings.completion.skip_final_approval:
            approval_path.parent.mkdir(parents=True, exist_ok=True)
            approval_path.write_text(
                json.dumps({"action": "approve", "exclude_files": []}, indent=2) + "\n",
                encoding="utf-8",
            )
            return {}

        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(
                ctx.files.completion_dir / "confirmation_prompt.md"
            ),
            build_confirmation_prompt(ctx.files),
        )
        send_to_role(
            ctx,
            "reviewer",
            prompt_file,
            display_label=role_display_label(
                ctx.files.feature_dir, "reviewer", state=state
            ),
        )
        return {}

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle events for completing phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for approval
        if path == "08_completion/approval.json":
            return self._handle_approval(state, ctx)

        # Check for changes requested
        if path == "08_completion/changes.md":
            return self._handle_changes_requested(state, ctx)

        return {}, None

    def _handle_approval(
        self,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle approval received."""
        approval_path = ctx.files.completion_dir / "approval.json"
        if not approval_path.exists():
            return {}, None

        try:
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}, None

        if payload.get("action") != "approve":
            return {}, None

        # Apply approved preferences
        apply_role_preferences(ctx, "reviewer")

        # Get changed paths
        changed_paths = _parse_changed_paths(
            _git_status_porcelain(ctx.files.project_dir)
        )
        exclude_files = {
            str(path).strip()
            for path in payload.get("exclude_files", [])
            if str(path).strip()
        }

        issue_number = (
            str(state.get("issue_number"))
            if state.get("issue_number") is not None
            else None
        )

        commit_message = COMPLETION_SERVICE.resolve_commit_message(
            payload_commit_message=payload.get("commit_message"),
            files=ctx.files,
            issue_number=issue_number,
        )

        result = COMPLETION_SERVICE.finalize_approval(
            files=ctx.files,
            github_config=ctx.github_config,
            gh_available=bool(state.get("gh_available")),
            issue_number=issue_number,
            commit_message=commit_message,
            changed_paths=[path for path in changed_paths if path not in exclude_files],
        )

        # Write last_completion.json
        feature_name = feature_slug_from_dir(ctx.files.feature_dir)
        branch_name = f"{ctx.github_config.branch_prefix}{feature_name}"
        if result.commit_hash is not None:
            paths = ProjectPaths.from_project(ctx.files.project_dir)
            summary_path = paths.last_completion
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(
                    {
                        "feature_name": feature_name,
                        "commit_hash": result.commit_hash,
                        "pr_url": result.pr_url,
                        "branch_name": branch_name,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        if result.commit_hash is not None:
            print("Completion approved and commit created.")
            print(f"Commit hash: {result.commit_hash}")
            if bool(state.get("gh_available")):
                if result.pr_url:
                    print(f"PR created: {result.pr_url}")
                else:
                    print("PR creation failed (commit preserved).")
        else:
            print(
                "Completion approved, but commit step failed or was skipped. Feature directory retained."
            )

        return {"__exit__": 0}, None

    def _handle_changes_requested(
        self,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle changes requested."""
        ctx.runtime.deactivate_many(("reviewer", "coder", "designer"))
        ctx.runtime.finish_many("coder")

        return {
            "subplan_count": 0,
            "review_iteration": 0,
            "completed_subplans": [],
            "last_event": "changes_requested",
        }, "planning"
