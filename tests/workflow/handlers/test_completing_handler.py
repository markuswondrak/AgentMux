"""Tests for CompletingHandler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import CompletingHandler


class TestCompletingHandler:
    """Tests for CompletingHandler."""

    def test_enter_writes_fallback_summary_when_missing(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """If 08_completion/summary.md is missing, enter() should create it.

        The completion UI reads summary.md; without it, users see
        "_No summary available._".
        """
        handler = CompletingHandler()

        # Ensure summary is absent
        summary_path = mock_ctx.files.completion_dir / "summary.md"
        if summary_path.exists():
            summary_path.unlink()

        state = {
            **empty_state,
            "review_results": {
                "reviewer_logic": {
                    "verdict": "fail",
                    "review_text": "verdict: fail\n\n## Summary\n\nLogic issue.\n",
                },
                "reviewer_expert": {
                    "verdict": "pass",
                    "review_text": "verdict: pass\n\n## Summary\n\nAll good.\n",
                },
            },
        }

        handler.enter(state, mock_ctx)

        assert summary_path.exists(), "enter() must create 08_completion/summary.md"
        text = summary_path.read_text(encoding="utf-8")
        assert "reviewer_logic" in text
        assert "reviewer_expert" in text
        assert "fail" in text
        assert "pass" in text

    def test_enter_writes_fix_request_fallback_when_review_results_absent(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Fallback: if review_results is absent but fix_request exists, use it."""
        handler = CompletingHandler()

        summary_path = mock_ctx.files.completion_dir / "summary.md"
        if summary_path.exists():
            summary_path.unlink()

        fix_request = mock_ctx.files.fix_request
        fix_request.parent.mkdir(parents=True, exist_ok=True)
        fix_request.write_text("Logic issues found in module X.", encoding="utf-8")

        handler.enter(empty_state, mock_ctx)

        assert summary_path.exists(), (
            "should create summary.md from fix_request fallback"
        )
        text = summary_path.read_text(encoding="utf-8")
        assert "Logic issues found in module X." in text

    def test_enter_writes_no_summary_when_neither_exists(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """If neither review_results nor fix_request exists, no summary is written."""
        handler = CompletingHandler()

        summary_path = mock_ctx.files.completion_dir / "summary.md"
        if summary_path.exists():
            summary_path.unlink()

        handler.enter(empty_state, mock_ctx)

        assert not summary_path.exists(), (
            "should not write summary.md when no data available"
        )

    def test_enter_writes_only_verdict_bullets_when_review_text_empty(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """review_results with empty review_text → verdict bullets only, no headers."""
        handler = CompletingHandler()

        summary_path = mock_ctx.files.completion_dir / "summary.md"
        if summary_path.exists():
            summary_path.unlink()

        state = {
            **empty_state,
            "review_results": {
                "reviewer_logic": {"verdict": "pass", "review_text": ""},
                "reviewer_quality": {"verdict": "pass", "review_text": "   "},
            },
        }

        handler.enter(state, mock_ctx)

        assert summary_path.exists()
        text = summary_path.read_text(encoding="utf-8")
        assert "reviewer_logic" in text
        assert "reviewer_quality" in text
        # No section headers for roles with empty text
        assert "### reviewer_logic" not in text
        assert "### reviewer_quality" not in text

    def test_enter_sends_confirmation_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() launches the native completion UI."""
        handler = CompletingHandler()

        handler.enter(empty_state, mock_ctx)

        mock_ctx.runtime.show_completion_ui.assert_called_once_with(
            mock_ctx.files.feature_dir
        )
        mock_ctx.runtime.send.assert_not_called()

    def test_enter_auto_approve_when_configured(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test auto-approval when skip_final_approval is set."""
        handler = CompletingHandler()
        mock_ctx.workflow_settings.completion.skip_final_approval = True

        handler.enter(empty_state, mock_ctx)

        # Should create approval.json with approve action
        approval_path = mock_ctx.files.completion_dir / "approval.json"
        assert approval_path.exists()
        payload = json.loads(approval_path.read_text())
        assert payload["action"] == "approve"

    def test_handle_approval_received(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test handling approval with commit and PR creation."""
        handler = CompletingHandler()
        event = WorkflowEvent(
            kind="approval_received", path="08_completion/approval.json"
        )

        # Create approval.json
        mock_ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.completion_dir / "approval.json").write_text(
            json.dumps(
                {
                    "action": "approve",
                    "exclude_files": [],
                    "commit_message": "feat: test commit",
                }
            )
        )

        with (
            patch(
                "agentmux.workflow.handlers.completing.CompletionService"
            ) as mock_service,
            patch(
                "agentmux.workflow.handlers.completing._git_status_porcelain"
            ) as mock_git,
            patch(
                "agentmux.workflow.handlers.completing._parse_changed_paths"
            ) as mock_parse,
        ):
            mock_instance = MagicMock()
            mock_instance.resolve_commit_message.return_value = "feat: test commit"
            mock_instance.finalize_approval.return_value = MagicMock(
                commit_hash="abc123",
                pr_url="https://github.com/test/pr/1",
                cleaned_up=True,
            )
            mock_service.return_value = mock_instance
            mock_git.return_value = "M  file.txt"
            mock_parse.return_value = ["file.txt"]

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            assert updates == {"__exit__": 0, "cleanup_feature_dir": False}
            assert next_phase is None

    def test_handle_changes_requested(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to planning when changes requested."""
        handler = CompletingHandler()
        event = WorkflowEvent(kind="changes_requested", path="08_completion/changes.md")

        # Create the changes file so is_ready predicate passes
        mock_ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.completion_dir / "changes.md").write_text("changes")

        # Set some state that should be reset
        state = {
            "subplan_count": 5,
            "review_iteration": 2,
            "completed_subplans": [1, 2, 3],
        }

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.deactivate_many.assert_called_once_with(
            ("reviewer", "coder", "designer")
        )
        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        assert next_phase == "planning"
        assert updates["subplan_count"] == 0
        assert updates["review_iteration"] == 0
        assert updates["completed_subplans"] == []
