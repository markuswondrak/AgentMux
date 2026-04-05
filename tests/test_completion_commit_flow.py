from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.completion import CompletionService
from agentmux.integrations.git_manager import GitBranchManager
from agentmux.sessions.state_store import create_feature_files, load_state
from agentmux.shared.models import (
    AgentConfig,
    CompletionSettings,
    GitHubConfig,
    WorkflowSettings,
)
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import CompletingHandler
from agentmux.workflow.prompts import build_reviewer_prompt
from agentmux.workflow.transitions import PipelineContext


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def send(
        self, role: str, prompt_file: Path, display_label: str | None = None
    ) -> None:
        self.calls.append(("send", role, prompt_file.name))

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))

    def show_completion_ui(self, feature_dir: Path) -> None:
        self.calls.append(("show_completion_ui", feature_dir))


def _make_ctx(
    feature_dir: Path, *, skip_final_approval: bool = False
) -> tuple[PipelineContext, dict]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "test", "session-x")
    files.plan.parent.mkdir(parents=True, exist_ok=True)
    files.plan.write_text("# Plan\n", encoding="utf-8")
    files.review.parent.mkdir(parents=True, exist_ok=True)
    files.review.write_text("verdict: pass\n", encoding="utf-8")
    agents = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "reviewer": AgentConfig(role="reviewer", cli="claude", model="sonnet", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    ctx = PipelineContext(
        files=files,
        runtime=_FakeRuntime(),
        agents=agents,
        max_review_iterations=3,
        prompts={},
        github_config=GitHubConfig(),
        workflow_settings=WorkflowSettings(
            completion=CompletionSettings(skip_final_approval=skip_final_approval),
        ),
    )
    return ctx, load_state(files.state)


class CompletionCommitFlowTests(unittest.TestCase):
    def test_completion_service_can_draft_commit_message_without_reviewer_payload(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, _ = _make_ctx(feature_dir)
            ctx.files.requirements.write_text(
                "\n".join(
                    [
                        "# Requirements",
                        "",
                        "## Initial Request",
                        "",
                        "complete approval flow without manual commit message",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            commit_message = CompletionService().draft_commit_message(
                files=ctx.files,
                issue_number="54",
            )

            self.assertIn("complete approval flow", commit_message)
            self.assertIn("#54", commit_message)

    def test_completion_service_resolve_commit_message_prefers_payload(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, _ = _make_ctx(feature_dir)
            service = CompletionService()

            with patch.object(
                service, "draft_commit_message", return_value="feat: drafted commit"
            ) as draft_mock:
                commit_message = service.resolve_commit_message(
                    payload_commit_message="  reviewer summary  ",
                    files=ctx.files,
                    issue_number=None,
                )

            self.assertEqual("reviewer summary", commit_message)
            draft_mock.assert_not_called()

            with patch.object(
                service, "draft_commit_message", return_value="feat: drafted commit"
            ) as draft_mock:
                fallback_commit = service.resolve_commit_message(
                    payload_commit_message="   ",
                    files=ctx.files,
                    issue_number="42",
                )

            self.assertEqual("feat: drafted commit", fallback_commit)
            draft_mock.assert_called_once_with(
                files=ctx.files,
                issue_number="42",
            )

    def test_completing_phase_on_enter_launches_completion_ui(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)

            CompletingHandler().enter(state, ctx)

            calls = ctx.runtime.calls
            self.assertTrue(
                any(c[0] == "show_completion_ui" for c in calls),
                f"Expected show_completion_ui call, got: {calls}",
            )
            # No prompt should be sent to any agent role
            self.assertFalse(
                any(c[0] == "send" for c in calls),
                f"Expected no send calls, got: {calls}",
            )

    def test_build_reviewer_review_prompt_requests_commit_message_on_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, _ = _make_ctx(feature_dir)

            prompt = build_reviewer_prompt(ctx.files, is_review=True)

            self.assertIn("verdict: pass", prompt)
            self.assertIn("commit_message", prompt)

    def test_approval_commits_changed_minus_exclusions_and_cleans_up_on_success(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)
            approval = {
                "action": "approve",
                "commit_message": "test commit",
                "exclude_files": ["tests/skip.py"],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )

            with (
                patch(
                    "agentmux.workflow.handlers.completing.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "status", "--porcelain"],
                        returncode=0,
                        stdout=(
                            " M agentmux/phases.py\n"
                            "?? tests/skip.py\n"
                            "R  old.py -> renamed.py\n"
                        ),
                        stderr="",
                    ),
                ),
                patch.object(
                    CompletionService,
                    "draft_commit_message",
                    return_value="feat: drafted commit",
                ),
                patch.object(
                    GitBranchManager,
                    "commit_on_branch",
                    return_value="abc123",
                ) as commit_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = CompletingHandler().handle_event(
                    event, state, ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            commit_mock.assert_called_once()

    def test_approval_uses_drafted_commit_message_when_payload_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)
            approval = {
                "action": "approve",
                "exclude_files": ["tests/skip.py"],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )

            with (
                patch(
                    "agentmux.workflow.handlers.completing.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "status", "--porcelain"],
                        returncode=0,
                        stdout=" M agentmux/phases.py\n?? tests/skip.py\n",
                        stderr="",
                    ),
                ),
                patch.object(
                    CompletionService,
                    "draft_commit_message",
                    return_value="feat: drafted commit",
                ) as draft_mock,
                patch.object(
                    GitBranchManager,
                    "commit_on_branch",
                    return_value="abc123",
                ) as commit_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = CompletingHandler().handle_event(
                    event, state, ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            draft_mock.assert_called_once_with(
                files=ctx.files,
                issue_number=None,
            )
            commit_mock.assert_called_once()

    def test_approval_failure_keeps_feature_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)
            approval = {
                "action": "approve",
                "commit_message": "test commit",
                "exclude_files": [],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )

            with (
                patch(
                    "agentmux.workflow.handlers.completing.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "status", "--porcelain"],
                        returncode=0,
                        stdout=" M agentmux/phases.py\n",
                        stderr="",
                    ),
                ),
                patch.object(
                    GitBranchManager,
                    "commit_on_branch",
                    return_value=None,
                ),
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = CompletingHandler().handle_event(
                    event, state, ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": False}, updates)
            self.assertIsNone(next_phase)

    def test_approval_with_gh_available_creates_pr_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "20260322-203228-my-feature"
            ctx, state = _make_ctx(feature_dir)
            state["gh_available"] = True
            state["issue_number"] = "42"
            approval = {
                "action": "approve",
                "commit_message": "test commit",
                "exclude_files": [],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )

            with (
                patch(
                    "agentmux.workflow.handlers.completing.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "status", "--porcelain"],
                        returncode=0,
                        stdout=" M agentmux/phases.py\n",
                        stderr="",
                    ),
                ),
                patch.object(
                    GitBranchManager,
                    "commit_on_branch",
                    return_value="abc123",
                ),
                patch(
                    "agentmux.integrations.completion.create_pr_only",
                    return_value={
                        "branch": "feature/my-feature",
                        "pr_url": "https://example/pr/1",
                    },
                ) as pr_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = CompletingHandler().handle_event(
                    event, state, ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            pr_mock.assert_called_once()

    def test_approval_with_gh_unavailable_skips_pr_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "20260322-203228-my-feature"
            ctx, state = _make_ctx(feature_dir)
            state["gh_available"] = False
            approval = {
                "action": "approve",
                "commit_message": "test commit",
                "exclude_files": [],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(
                json.dumps(approval), encoding="utf-8"
            )

            with (
                patch(
                    "agentmux.workflow.handlers.completing.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "status", "--porcelain"],
                        returncode=0,
                        stdout=" M agentmux/phases.py\n",
                        stderr="",
                    ),
                ),
                patch.object(
                    GitBranchManager,
                    "commit_on_branch",
                    return_value="abc123",
                ),
                patch("agentmux.integrations.completion.create_pr_only") as pr_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = CompletingHandler().handle_event(
                    event, state, ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            pr_mock.assert_not_called()

    def test_skip_final_approval_bypasses_reviewer_prompt_and_prepares_auto_approval(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir, skip_final_approval=True)

            with patch.object(ctx.runtime, "send") as send_mock:
                CompletingHandler().enter(state, ctx)

            send_mock.assert_not_called()
            approval = json.loads(
                (ctx.files.completion_dir / "approval.json").read_text(encoding="utf-8")
            )
            self.assertEqual({"action": "approve", "exclude_files": []}, approval)

    def test_skip_final_approval_auto_approval_reaches_commit_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir, skip_final_approval=True)
            handler = CompletingHandler()
            handler.enter(state, ctx)

            # Check that approval.json was created
            self.assertTrue((ctx.files.completion_dir / "approval.json").exists())

            with (
                patch(
                    "agentmux.workflow.handlers.completing.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        args=["git", "status", "--porcelain"],
                        returncode=0,
                        stdout=" M agentmux/phases.py\n",
                        stderr="",
                    ),
                ),
                patch.object(
                    CompletionService,
                    "draft_commit_message",
                    return_value="feat: drafted commit",
                ) as draft_mock,
                patch.object(
                    GitBranchManager,
                    "commit_on_branch",
                    return_value="abc123",
                ) as commit_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = handler.handle_event(event, state, ctx)

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            draft_mock.assert_called_once_with(
                files=ctx.files,
                issue_number=None,
            )
            commit_mock.assert_called_once()

    def test_changes_requested_deactivates_reviewer_and_resets_for_replanning(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)
            state["phase"] = "completing"
            state["subplan_count"] = 3
            state["review_iteration"] = 2
            state["implementation_group_total"] = 2
            state["implementation_group_index"] = 1
            state["implementation_group_mode"] = "parallel"
            state["implementation_active_plan_ids"] = ["plan_3", "plan_4"]
            state["implementation_completed_group_ids"] = ["group_1"]

            event = WorkflowEvent(
                kind="changes_requested",
                path="08_completion/changes.md",
                payload={},
            )
            updates, next_phase = CompletingHandler().handle_event(event, state, ctx)

            self.assertEqual("planning", next_phase)
            self.assertIn(
                ("deactivate_many", ("reviewer", "coder", "designer")),
                ctx.runtime.calls,
            )
            self.assertIn(("finish_many", "coder"), ctx.runtime.calls)

            self.assertEqual("changes_requested", updates.get("last_event"))
            self.assertEqual(0, updates.get("subplan_count"))
            self.assertEqual(0, updates.get("review_iteration"))
            self.assertEqual([], updates.get("completed_subplans"))


if __name__ == "__main__":
    unittest.main()
