from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.completion import CompletionService
from agentmux.shared.models import AgentConfig, CompletionSettings, GitHubConfig, WorkflowSettings
from agentmux.workflow.phases import CompletingPhase
from agentmux.workflow.prompts import build_confirmation_prompt
from agentmux.sessions.state_store import create_feature_files, load_state
from agentmux.workflow.transitions import EXIT_SUCCESS, PipelineContext


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def send(self, role: str, prompt_file: Path, display_label: str | None = None) -> None:
        self.calls.append(("send", role, prompt_file.name))

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))


def _make_ctx(feature_dir: Path, *, skip_final_approval: bool = False) -> tuple[PipelineContext, dict]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "test", "session-x")
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
    def test_completion_service_can_draft_commit_message_without_reviewer_payload(self) -> None:
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

    def test_completing_phase_on_enter_sends_confirmation_prompt_to_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)

            with patch.object(ctx.runtime, "send") as send_mock:
                CompletingPhase().on_enter(state, ctx)

            sent_role = send_mock.call_args.args[0]
            sent_prompt = send_mock.call_args.args[1]
            self.assertEqual("reviewer", sent_role)
            self.assertEqual("confirmation_prompt.md", sent_prompt.name)

    def test_build_confirmation_prompt_includes_git_status_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, _ = _make_ctx(feature_dir)
            status_output = " M agentmux/phases.py\n?? tests/test_completion_commit_flow.py\n"

            with patch(
                "agentmux.workflow.prompts.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=status_output,
                    stderr="",
                ),
            ) as run_mock:
                prompt = build_confirmation_prompt(ctx.files)

            self.assertIn(status_output.strip(), prompt)
            run_mock.assert_called_once_with(
                ["git", "status", "--porcelain"],
                cwd=ctx.files.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )

    def test_build_confirmation_prompt_does_not_request_commit_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, _ = _make_ctx(feature_dir)

            prompt = build_confirmation_prompt(ctx.files)

            self.assertIn('"action": "approve"', prompt)
            self.assertIn('"exclude_files": ["relative/path"]', prompt)
            self.assertNotIn("commit_message", prompt)

    def test_approval_commits_changed_minus_exclusions_and_cleans_up_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)
            approval = {
                "action": "approve",
                "commit_message": "test commit",
                "exclude_files": ["tests/skip.py"],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

            with patch(
                "agentmux.workflow.phases.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=" M agentmux/phases.py\n?? tests/skip.py\nR  old.py -> renamed.py\n",
                    stderr="",
                ),
            ), patch.object(
                CompletionService,
                "draft_commit_message",
                return_value="feat: drafted commit",
            ), patch("agentmux.integrations.completion.commit_changes", return_value="abc123") as commit_mock, patch(
                "agentmux.integrations.completion.cleanup_feature_dir"
            ) as cleanup_mock:
                result = CompletingPhase().handle_event(state, "approval_received", ctx)

            self.assertEqual(EXIT_SUCCESS, result)
            commit_mock.assert_called_once_with(
                ctx.files.project_dir,
                "feat: drafted commit",
                ["agentmux/phases.py", "renamed.py"],
            )
            cleanup_mock.assert_called_once_with(ctx.files.feature_dir)

    def test_approval_uses_drafted_commit_message_when_payload_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir)
            approval = {
                "action": "approve",
                "exclude_files": ["tests/skip.py"],
            }
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

            with patch(
                "agentmux.workflow.phases.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=" M agentmux/phases.py\n?? tests/skip.py\n",
                    stderr="",
                ),
            ), patch.object(
                CompletionService,
                "draft_commit_message",
                return_value="feat: drafted commit",
            ) as draft_mock, patch("agentmux.integrations.completion.commit_changes", return_value="abc123") as commit_mock, patch(
                "agentmux.integrations.completion.cleanup_feature_dir"
            ):
                result = CompletingPhase().handle_event(state, "approval_received", ctx)

            self.assertEqual(EXIT_SUCCESS, result)
            draft_mock.assert_called_once_with(
                files=ctx.files,
                issue_number=None,
            )
            commit_mock.assert_called_once_with(
                ctx.files.project_dir,
                "feat: drafted commit",
                ["agentmux/phases.py"],
            )

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
            (ctx.files.completion_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

            with patch(
                "agentmux.workflow.phases.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=" M agentmux/phases.py\n",
                    stderr="",
                ),
            ), patch("agentmux.integrations.completion.commit_changes", return_value=None), patch(
                "agentmux.integrations.completion.cleanup_feature_dir"
            ) as cleanup_mock:
                result = CompletingPhase().handle_event(state, "approval_received", ctx)

            self.assertEqual(EXIT_SUCCESS, result)
            cleanup_mock.assert_not_called()

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
            (ctx.files.completion_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

            with patch(
                "agentmux.workflow.phases.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=" M agentmux/phases.py\n",
                    stderr="",
                ),
            ), patch("agentmux.integrations.completion.commit_changes", return_value="abc123"), patch(
                "agentmux.integrations.completion.create_branch_and_pr",
                return_value={"branch": "feature/my-feature", "pr_url": "https://example/pr/1"},
            ) as pr_mock, patch("agentmux.integrations.completion.cleanup_feature_dir") as cleanup_mock:
                result = CompletingPhase().handle_event(state, "approval_received", ctx)

            self.assertEqual(EXIT_SUCCESS, result)
            pr_mock.assert_called_once_with(
                project_dir=ctx.files.project_dir,
                feature_slug="my-feature",
                github_config=ctx.github_config,
                issue_number="42",
                feature_dir=ctx.files.feature_dir,
            )
            cleanup_mock.assert_called_once_with(ctx.files.feature_dir)

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
            (ctx.files.completion_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

            with patch(
                "agentmux.workflow.phases.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=" M agentmux/phases.py\n",
                    stderr="",
                ),
            ), patch("agentmux.integrations.completion.commit_changes", return_value="abc123"), patch(
                "agentmux.integrations.completion.create_branch_and_pr"
            ) as pr_mock, patch("agentmux.integrations.completion.cleanup_feature_dir") as cleanup_mock:
                result = CompletingPhase().handle_event(state, "approval_received", ctx)

            self.assertEqual(EXIT_SUCCESS, result)
            pr_mock.assert_not_called()
            cleanup_mock.assert_called_once_with(ctx.files.feature_dir)

    def test_skip_final_approval_bypasses_reviewer_prompt_and_prepares_auto_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir, skip_final_approval=True)

            with patch.object(ctx.runtime, "send") as send_mock:
                CompletingPhase().on_enter(state, ctx)

            send_mock.assert_not_called()
            approval = json.loads((ctx.files.completion_dir / "approval.json").read_text(encoding="utf-8"))
            self.assertEqual({"action": "approve", "exclude_files": []}, approval)

    def test_skip_final_approval_auto_approval_reaches_commit_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state = _make_ctx(feature_dir, skip_final_approval=True)
            phase = CompletingPhase()
            phase.on_enter(state, ctx)

            event = phase.detect_event(state, ctx)
            self.assertEqual("approval_received", event)

            with patch(
                "agentmux.workflow.phases.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=" M agentmux/phases.py\n",
                    stderr="",
                ),
            ), patch(
                "agentmux.integrations.completion.commit_changes",
                return_value="abc123",
            ) as commit_mock, patch("agentmux.integrations.completion.cleanup_feature_dir") as cleanup_mock:
                result = phase.handle_event(state, "approval_received", ctx)

            self.assertEqual(EXIT_SUCCESS, result)
            commit_mock.assert_called_once()
            cleanup_mock.assert_called_once_with(ctx.files.feature_dir)

    def test_changes_requested_deactivates_reviewer_and_resets_for_replanning(self) -> None:
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

            result = CompletingPhase().handle_event(state, "changes_requested", ctx)

            self.assertIsNone(result)
            self.assertIn(
                ("deactivate_many", ("reviewer", "coder", "designer")),
                ctx.runtime.calls,
            )
            self.assertIn(("finish_many", "coder"), ctx.runtime.calls)

            updated = load_state(ctx.files.state)
            self.assertEqual("planning", updated["phase"])
            self.assertEqual("changes_requested", updated["last_event"])
            self.assertEqual(0, updated["subplan_count"])
            self.assertEqual(0, updated["review_iteration"])
            self.assertEqual(0, updated["implementation_group_total"])
            self.assertEqual(0, updated["implementation_group_index"])
            self.assertIsNone(updated["implementation_group_mode"])
            self.assertEqual([], updated["implementation_active_plan_ids"])
            self.assertEqual([], updated["implementation_completed_group_ids"])


if __name__ == "__main__":
    unittest.main()
