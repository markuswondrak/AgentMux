"""Tests for ReviewingHandler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import yaml

from agentmux.workflow.event_catalog import EVENT_REVIEW_PASSED
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import ReviewingHandler
from agentmux.workflow.phase_result import PhaseResult


class TestReviewingHandler:
    """Tests for ReviewingHandler."""

    def test_enter_sends_reviewer_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() dispatches reviewers via ctx.runtime."""
        handler = ReviewingHandler()

        with patch(
            "agentmux.workflow.handlers.reviewing.select_reviewer_roles"
        ) as mock_select:
            # Mock to return a single reviewer for simplicity
            mock_select.return_value = ["reviewer_logic"]

            result = handler.enter(empty_state, mock_ctx)

            # Should return PhaseResult with updates
            assert isinstance(result, PhaseResult)
            # select_reviewer_roles should be called
            mock_select.assert_called_once()
            # ctx.runtime.send_reviewers_many should be called via the mock
            mock_ctx.runtime.send_reviewers_many.assert_called_once()

    def test_handle_review_passed(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test that VERDICT:PASS stays in reviewing and requests summary."""
        handler = ReviewingHandler()

        role = "reviewer_logic"
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / f"review_{role}.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "pass",
                    "summary": "Looks good!",
                    "findings": [],
                    "commit_message": "feat: all done",
                },
                default_flow_style=False,
            )
        )
        # Create review.md for summary prompt include
        (mock_ctx.files.review_dir / "review.md").write_text(
            "verdict: pass\n\n## Summary\n\nLooks good!", encoding="utf-8"
        )
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        # Stays in reviewing, awaiting summary
        assert next_phase is None
        assert updates.get("awaiting_summary") is True
        assert updates.get("last_event") == EVENT_REVIEW_PASSED

    def test_handle_review_yaml_pass_materializes_review_md(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Review tool event writes both review.yaml and review.md."""
        handler = ReviewingHandler()

        role = "reviewer_logic"
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / f"review_{role}.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "pass",
                    "summary": "Looks good!",
                    "findings": [],
                    "commit_message": "feat: done",
                },
                default_flow_style=False,
            )
        )
        # Create review.md for summary prompt include
        (mock_ctx.files.review_dir / "review.md").write_text(
            "verdict: pass\n\n## Summary\n\nLooks good!", encoding="utf-8"
        )
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        assert next_phase is None
        assert updates.get("awaiting_summary") is True
        review_yaml_path = mock_ctx.files.review_dir / f"review_{role}.yaml"
        assert review_yaml_path.exists()
        assert mock_ctx.files.review.exists()
        assert mock_ctx.files.review.read_text(encoding="utf-8").startswith(
            "verdict: pass"
        )

    def test_handle_review_failed_under_max_iterations(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to fixing when under max iterations."""
        handler = ReviewingHandler()

        role = "reviewer_logic"
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / f"review_{role}.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "fail",
                    "summary": "Needs fixes",
                    "findings": [
                        {
                            "location": "src/example.py:10",
                            "issue": "Missing validation",
                            "severity": "high",
                            "recommendation": "Add check",
                        }
                    ],
                    "commit_message": "",
                },
                default_flow_style=False,
            )
        )
        # Create review.md for summary prompt include
        (mock_ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\nNeeds fixes", encoding="utf-8"
        )
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        assert next_phase == "fixing"
        assert updates["review_iteration"] == 1
        assert mock_ctx.files.fix_request.exists()

    def test_handle_review_yaml_fail_creates_fix_request(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Review tool event with fail verdict creates fix_request.txt."""
        handler = ReviewingHandler()

        role = "reviewer_logic"
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / f"review_{role}.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "fail",
                    "summary": "Needs fixes",
                    "findings": [
                        {
                            "location": "src/example.py:10",
                            "issue": "Missing validation",
                            "severity": "high",
                            "recommendation": "Add the missing check.",
                        }
                    ],
                    "commit_message": "",
                },
                default_flow_style=False,
            )
        )
        # Create review.md for summary prompt include
        (mock_ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\nNeeds fixes", encoding="utf-8"
        )
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        assert next_phase == "fixing"
        assert updates["review_iteration"] == 1
        assert mock_ctx.files.fix_request.exists()
        # fix_request contains aggregated feedback
        assert "Missing validation" in mock_ctx.files.fix_request.read_text(
            encoding="utf-8"
        )

    def test_handle_review_failed_at_max_iterations(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to completing when max iterations reached."""
        handler = ReviewingHandler()

        role = "reviewer_logic"
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / f"review_{role}.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "fail",
                    "summary": "Still failing",
                    "findings": [
                        {
                            "location": "src/example.py:10",
                            "issue": "Persistent issue",
                            "severity": "high",
                            "recommendation": "Fix it",
                        }
                    ],
                    "commit_message": "",
                },
                default_flow_style=False,
            )
        )
        # Create review.md for summary prompt include
        (mock_ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\nStill failing", encoding="utf-8"
        )
        event = WorkflowEvent(kind="review", payload={"payload": {}})

        # Set state at max iterations
        state = {
            "review_iteration": 3,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        assert next_phase == "completing"
