"""Unit tests for event-driven phase handlers.

These tests verify that each phase handler correctly:
1. Sends prompts on enter()
2. Handles events and returns appropriate state updates
3. Transitions to the correct next phase
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import (
    PHASE_HANDLERS,
    CompletingHandler,
    DesigningHandler,
    FailedHandler,
    FixingHandler,
    ImplementingHandler,
    PlanningHandler,
    ProductManagementHandler,
    ReviewingHandler,
)

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


@pytest.fixture
def mock_ctx(tmp_path: Path) -> MagicMock:
    """Create a mock PipelineContext with realistic file structure."""
    ctx = MagicMock()
    ctx.files.feature_dir = tmp_path
    ctx.files.product_management_dir = tmp_path / "01_product_management"
    ctx.files.planning_dir = tmp_path / "02_planning"
    ctx.files.design_dir = tmp_path / "04_design"
    ctx.files.implementation_dir = tmp_path / "05_implementation"
    ctx.files.review_dir = tmp_path / "06_review"
    ctx.files.completion_dir = tmp_path / "08_completion"
    ctx.files.research_dir = tmp_path / "research"
    ctx.files.changes = tmp_path / "02_planning" / "changes.md"
    ctx.files.plan = tmp_path / "02_planning" / "plan.md"
    ctx.files.tasks = tmp_path / "02_planning" / "tasks.md"
    ctx.files.design = tmp_path / "04_design" / "design.md"
    ctx.files.review = tmp_path / "06_review" / "review.md"
    ctx.files.fix_request = tmp_path / "06_review" / "fix_request.txt"
    ctx.files.requirements = tmp_path / "requirements.md"
    ctx.files.pm_preference_proposal = (
        tmp_path / "01_product_management" / "preference_proposal.json"
    )
    ctx.files.architect_preference_proposal = (
        tmp_path / "02_planning" / "preference_proposal.json"
    )
    ctx.files.reviewer_preference_proposal = (
        tmp_path / "06_review" / "preference_proposal.json"
    )
    ctx.files.project_dir = tmp_path.parent
    ctx.files.relative_path = lambda p: str(p.relative_to(tmp_path))
    ctx.files.state = tmp_path / "state.json"
    ctx.agents = {}
    ctx.max_review_iterations = 3
    ctx.workflow_settings.completion.skip_final_approval = False
    ctx.github_config.branch_prefix = "feature/"
    return ctx


@pytest.fixture
def empty_state() -> dict:
    """Create an empty state dict."""
    return {}


class TestProductManagementHandler:
    """Tests for ProductManagementHandler."""

    def test_enter_sends_prompt(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test that enter() sends product-manager prompt."""
        handler = ProductManagementHandler()

        with (
            patch(
                "agentmux.workflow.handlers.product_management.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.product_management.send_to_role"
            ) as mock_send,
            patch(
                "agentmux.workflow.handlers.product_management.build_product_manager_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "mock prompt content"

            updates = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_write.assert_called_once()
            mock_send.assert_called_once_with(
                mock_ctx, "product-manager", Path("/mock/prompt.md")
            )
            assert updates == {}

    def test_handle_pm_completed(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test handling of pm_done marker."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(kind="file.created", path="01_product_management/done")

        with patch(
            "agentmux.workflow.handlers.product_management.apply_role_preferences"
        ) as mock_apply:
            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            mock_ctx.runtime.kill_primary.assert_called_once_with("product-manager")
            mock_apply.assert_called_once_with(mock_ctx, "product-manager")
            assert updates == {"last_event": "pm_completed"}
            assert next_phase == "planning"

    def test_handle_code_research_request(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test dispatching code-researcher task."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="file.created", path="03_research/code-auth/request.md"
        )

        # Create the request file
        research_dir = mock_ctx.files.research_dir / "code-auth"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "request.md").write_text("research auth")

        with (
            patch("agentmux.workflow.prompts.write_prompt_file") as mock_write,
            patch(
                "agentmux.workflow.prompts.build_code_researcher_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "research prompt"

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            mock_ctx.runtime.spawn_task.assert_called_once_with(
                "code-researcher", "auth", research_dir
            )
            assert "research_tasks" in updates
            assert updates["research_tasks"]["auth"] == "dispatched"
            assert next_phase is None

    def test_handle_web_research_request(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test dispatching web-researcher task."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="file.created", path="03_research/web-api/request.md"
        )

        # Create the request file
        research_dir = mock_ctx.files.research_dir / "web-api"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "request.md").write_text("research api")

        with (
            patch("agentmux.workflow.prompts.write_prompt_file") as mock_write,
            patch(
                "agentmux.workflow.prompts.build_web_researcher_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "research prompt"

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            mock_ctx.runtime.spawn_task.assert_called_once_with(
                "web-researcher", "api", research_dir
            )
            assert "web_research_tasks" in updates
            assert updates["web_research_tasks"]["api"] == "dispatched"

    def test_handle_code_research_done(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test handling code-research completion."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(kind="file.created", path="03_research/code-auth/done")

        # Setup state with dispatched task
        state = {"research_tasks": {"auth": "dispatched"}}

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_task.assert_called_once_with("code-researcher", "auth")
        mock_ctx.runtime.notify.assert_called_once()
        assert updates["research_tasks"]["auth"] == "done"

    def test_skip_already_dispatched_research(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that already dispatched research is not re-dispatched."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="file.created", path="03_research/code-auth/request.md"
        )

        # Setup state with already dispatched task
        state = {"research_tasks": {"auth": "dispatched"}}

        with (
            patch("agentmux.workflow.prompts.write_prompt_file"),
            patch("agentmux.workflow.prompts.build_code_researcher_prompt"),
        ):
            updates, next_phase = handler.handle_event(event, state, mock_ctx)

            mock_ctx.runtime.spawn_task.assert_not_called()
            assert updates == {}


class TestPlanningHandler:
    """Tests for PlanningHandler."""

    def test_enter_sends_architect_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends architect prompt."""
        handler = PlanningHandler()

        with (
            patch(
                "agentmux.workflow.handlers.planning.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.planning.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.planning.build_architect_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "architect prompt"

            updates = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once_with(
                mock_ctx, "architect", Path("/mock/prompt.md")
            )

    def test_enter_sends_change_prompt_on_replan(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends change prompt when replanning."""
        handler = PlanningHandler()
        state = {"last_event": "changes_requested"}

        # Create changes.md to trigger replan mode
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.changes.write_text("changes requested")

        with (
            patch(
                "agentmux.workflow.handlers.planning.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.planning.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.planning.build_change_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "change prompt"

            updates = handler.enter(state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once_with(
                mock_ctx, "architect", Path("/mock/prompt.md")
            )

    def test_handle_plan_written_all_files_exist(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition when all plan files exist."""
        handler = PlanningHandler()
        event = WorkflowEvent(kind="file.created", path="02_planning/plan.md")

        # Create all required files
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.plan.write_text("plan")
        mock_ctx.files.tasks.write_text("tasks")
        (mock_ctx.files.planning_dir / "plan_meta.json").write_text(
            '{"needs_design": false}'
        )

        with (
            patch("agentmux.workflow.handlers.planning.load_execution_plan"),
            patch("agentmux.workflow.handlers.planning.load_plan_meta") as mock_meta,
            patch(
                "agentmux.workflow.handlers.planning.apply_role_preferences"
            ) as mock_apply,
        ):
            mock_meta.return_value = {"needs_design": False}

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            assert next_phase == "implementing"
            mock_ctx.runtime.kill_primary.assert_called_once_with("architect")
            mock_apply.assert_called_once_with(mock_ctx, "architect")

    def test_handle_plan_written_needs_design(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to designing when needs_design is true."""
        handler = PlanningHandler()
        event = WorkflowEvent(kind="file.created", path="02_planning/plan.md")

        # Create all required files
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.plan.write_text("plan")
        mock_ctx.files.tasks.write_text("tasks")
        (mock_ctx.files.planning_dir / "plan_meta.json").write_text(
            '{"needs_design": true}'
        )

        # Add designer to agents
        mock_ctx.agents = {"designer": MagicMock()}

        with (
            patch("agentmux.workflow.handlers.planning.load_execution_plan"),
            patch("agentmux.workflow.handlers.planning.load_plan_meta") as mock_meta,
            patch("agentmux.workflow.handlers.planning.apply_role_preferences"),
        ):
            mock_meta.return_value = {"needs_design": True}

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            assert next_phase == "designing"

    def test_deletes_changes_md_on_transition(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that changes.md is deleted on plan_written transition."""
        handler = PlanningHandler()
        event = WorkflowEvent(kind="file.created", path="02_planning/plan.md")

        # Create all required files including changes.md
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.plan.write_text("plan")
        mock_ctx.files.tasks.write_text("tasks")
        (mock_ctx.files.planning_dir / "plan_meta.json").write_text("{}")
        mock_ctx.files.changes.write_text("changes")

        with (
            patch("agentmux.workflow.handlers.planning.load_execution_plan"),
            patch("agentmux.workflow.handlers.planning.load_plan_meta") as mock_meta,
            patch("agentmux.workflow.handlers.planning.apply_role_preferences"),
        ):
            mock_meta.return_value = {}

            handler.handle_event(event, empty_state, mock_ctx)

            assert not mock_ctx.files.changes.exists()


class TestDesigningHandler:
    """Tests for DesigningHandler."""

    def test_enter_sends_designer_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends designer prompt."""
        handler = DesigningHandler()

        with (
            patch(
                "agentmux.workflow.handlers.designing.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.designing.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.designing.build_designer_prompt"
            ) as mock_build,
            patch(
                "agentmux.workflow.handlers.designing.role_display_label"
            ) as mock_label,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "designer prompt"
            mock_label.return_value = "[designer] design"

            updates = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once_with(
                mock_ctx,
                "designer",
                Path("/mock/prompt.md"),
                display_label="[designer] design",
            )

    def test_handle_design_written(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition on design.md creation."""
        handler = DesigningHandler()
        event = WorkflowEvent(kind="file.created", path="04_design/design.md")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.deactivate.assert_called_once_with("designer")
        assert next_phase == "implementing"


class TestImplementingHandler:
    """Tests for ImplementingHandler."""

    def test_enter_resets_markers_and_dispatches(self, mock_ctx: MagicMock) -> None:
        """Test that enter() resets markers and dispatches first group."""
        handler = ImplementingHandler()
        state = {"last_event": "plan_written"}

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "First Plan"}],
                        }
                    ],
                }
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch(
                "agentmux.workflow.handlers.implementing.reset_markers"
            ) as mock_reset,
            patch(
                "agentmux.workflow.handlers.implementing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.implementing.build_coder_subplan_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "coder prompt"

            updates = handler.enter(state, mock_ctx)

            mock_reset.assert_called_once()
            mock_ctx.runtime.kill_primary.assert_called_once_with("coder")
            assert "subplan_count" in updates
            assert updates["subplan_count"] == 1

    def test_handle_subplan_completed_parallel_mode(self, mock_ctx: MagicMock) -> None:
        """Test handling subplan completion in parallel mode."""
        handler = ImplementingHandler()
        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")

        # Setup state for parallel group
        state = {
            "implementation_group_index": 1,
            "implementation_group_mode": "parallel",
            "implementation_active_plan_ids": ["plan_1", "plan_2"],
        }

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "parallel",
                            "plans": [
                                {"file": "plan_1.md", "name": "Plan 1"},
                                {"file": "plan_2.md", "name": "Plan 2"},
                            ],
                        }
                    ],
                }
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        (mock_ctx.files.planning_dir / "plan_2.md").write_text("plan 2")
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.hide_task.assert_called_once_with("coder", 1)
        assert "completed_subplans" in updates
        assert 1 in updates["completed_subplans"]
        assert next_phase is None  # Not all subplans complete yet

    def test_handle_implementation_completed(self, mock_ctx: MagicMock) -> None:
        """Test transition when all implementation is complete."""
        handler = ImplementingHandler()
        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")

        # Setup state with all markers complete
        state = {
            "implementation_group_index": 1,
            "implementation_group_mode": "serial",
            "implementation_active_plan_ids": ["plan_1"],
        }

        # Create execution plan and done marker
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                        }
                    ],
                }
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.implementation_dir / "done_1").write_text("")

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"


class TestReviewingHandler:
    """Tests for ReviewingHandler."""

    def test_enter_sends_reviewer_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends reviewer prompt."""
        handler = ReviewingHandler()

        with (
            patch(
                "agentmux.workflow.handlers.reviewing.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.reviewing.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.reviewing.build_reviewer_prompt"
            ) as mock_build,
            patch(
                "agentmux.workflow.handlers.reviewing.role_display_label"
            ) as mock_label,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "reviewer prompt"
            mock_label.return_value = "[reviewer] iteration 1"

            updates = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files, is_review=True)
            mock_send.assert_called_once()

    def test_handle_review_passed(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test transition on verdict: pass."""
        handler = ReviewingHandler()
        event = WorkflowEvent(kind="file.created", path="06_review/review.md")

        # Create review.md with pass verdict
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.review.write_text("verdict: pass\n\nLooks good!")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.kill_primary.assert_called_once_with("coder")
        assert next_phase == "completing"

    def test_handle_review_failed_under_max_iterations(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to fixing when under max iterations."""
        handler = ReviewingHandler()
        event = WorkflowEvent(kind="file.created", path="06_review/review.md")

        # Create review.md with fail verdict
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.review.write_text("verdict: fail\n\nNeeds fixes")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert next_phase == "fixing"
        assert updates["review_iteration"] == 1
        assert mock_ctx.files.fix_request.exists()

    def test_handle_review_failed_at_max_iterations(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to completing when max iterations reached."""
        handler = ReviewingHandler()
        event = WorkflowEvent(kind="file.created", path="06_review/review.md")

        # Create review.md with fail verdict
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.review.write_text("verdict: fail\n\nStill failing")

        # Set state at max iterations
        state = {"review_iteration": 3}

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        assert next_phase == "completing"


class TestFixingHandler:
    """Tests for FixingHandler."""

    def test_enter_sends_fix_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends fix prompt."""
        handler = FixingHandler()

        with (
            patch("agentmux.workflow.handlers.fixing.write_prompt_file") as mock_write,
            patch("agentmux.workflow.handlers.fixing.send_to_role") as mock_send,
            patch("agentmux.workflow.handlers.fixing.build_fix_prompt") as mock_build,
            patch("agentmux.workflow.handlers.fixing.role_display_label") as mock_label,
            patch("agentmux.workflow.handlers.fixing.reset_markers"),
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "fix prompt"
            mock_label.return_value = "[coder] fix 1"

            updates = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once_with(
                mock_ctx,
                "coder",
                Path("/mock/prompt.md"),
                display_label="[coder] fix 1",
            )

    def test_handle_implementation_completed(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition on done_1 marker."""
        handler = FixingHandler()
        event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"


class TestCompletingHandler:
    """Tests for CompletingHandler."""

    def test_enter_sends_confirmation_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends confirmation prompt."""
        handler = CompletingHandler()

        with (
            patch(
                "agentmux.workflow.handlers.completing.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.completing.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.completing.build_confirmation_prompt"
            ) as mock_build,
            patch(
                "agentmux.workflow.handlers.completing.role_display_label"
            ) as mock_label,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "confirmation prompt"
            mock_label.return_value = "[reviewer] iteration 1"

            updates = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files)
            mock_send.assert_called_once()

    def test_enter_auto_approve_when_configured(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test auto-approval when skip_final_approval is set."""
        handler = CompletingHandler()
        mock_ctx.workflow_settings.completion.skip_final_approval = True

        updates = handler.enter(empty_state, mock_ctx)

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
        event = WorkflowEvent(kind="file.created", path="08_completion/approval.json")

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
            patch(
                "agentmux.workflow.handlers.completing.apply_role_preferences"
            ) as mock_apply,
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
            mock_apply.assert_called_once_with(mock_ctx, "reviewer")

    def test_handle_changes_requested(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to planning when changes requested."""
        handler = CompletingHandler()
        event = WorkflowEvent(kind="file.created", path="08_completion/changes.md")

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


class TestFailedHandler:
    """Tests for FailedHandler."""

    def test_enter_returns_empty(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test that enter() returns empty updates."""
        handler = FailedHandler()

        updates = handler.enter(empty_state, mock_ctx)

        assert updates == {}

    def test_handle_event_returns_exit_failure(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that any event returns exit failure."""
        handler = FailedHandler()
        event = WorkflowEvent(kind="file.created", path="any/path")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert updates == {"__exit__": 1}
        assert next_phase is None


class TestPhaseHandlersRegistry:
    """Tests for the PHASE_HANDLERS registry."""

    def test_all_phases_registered(self) -> None:
        """Test that all expected phases are in the registry."""
        expected_phases = [
            "product_management",
            "planning",
            "designing",
            "implementing",
            "reviewing",
            "fixing",
            "completing",
            "failed",
        ]

        for phase in expected_phases:
            assert phase in PHASE_HANDLERS, f"Phase {phase} not found in registry"

    def test_all_handlers_implement_protocol(self) -> None:
        """Test that all handlers implement the PhaseHandler protocol."""
        from agentmux.workflow.event_router import PhaseHandler

        for name, handler in PHASE_HANDLERS.items():
            assert hasattr(handler, "enter"), f"{name} missing enter()"
            assert hasattr(handler, "handle_event"), f"{name} missing handle_event()"
            assert callable(handler.enter), f"{name}.enter not callable"
            assert callable(handler.handle_event), f"{name}.handle_event not callable"


class TestHandlerEdgeCases:
    """Edge case tests for handlers."""

    def test_non_file_event_ignored(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that non-file events are ignored."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(kind="interruption.pane_exited", payload={"pane": "test"})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert updates == {}
        assert next_phase is None

    def test_unrelated_path_ignored(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that unrelated paths are ignored."""
        handler = PlanningHandler()
        event = WorkflowEvent(kind="file.created", path="some/random/file.txt")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert updates == {}
        assert next_phase is None

    def test_handler_preserves_existing_state(self, mock_ctx: MagicMock) -> None:
        """Test that handlers preserve existing state fields."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="file.created", path="03_research/code-auth/request.md"
        )

        # Create the request file
        research_dir = mock_ctx.files.research_dir / "code-auth"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "request.md").write_text("research auth")

        # State with existing fields
        state = {
            "existing_field": "value",
            "another_field": 123,
        }

        with (
            patch("agentmux.workflow.prompts.write_prompt_file"),
            patch("agentmux.workflow.prompts.build_code_researcher_prompt"),
        ):
            updates, _ = handler.handle_event(event, state, mock_ctx)

            # Should only add research_tasks, not remove existing fields
            assert "existing_field" not in updates  # Handlers return only updates
            assert "research_tasks" in updates


class TestPhaseHelpers:
    """Tests for extracted phase helper functions."""

    def test_filter_file_created_event_returns_path(self) -> None:
        """Test that file.created events return their path."""
        from agentmux.workflow.phase_helpers import filter_file_created_event
        from agentmux.workflow.event_router import WorkflowEvent

        event = WorkflowEvent(kind="file.created", path="some/path.txt")
        assert filter_file_created_event(event) == "some/path.txt"

    def test_filter_file_created_event_returns_none_for_other_events(self) -> None:
        """Test that non-file.created events return None."""
        from agentmux.workflow.phase_helpers import filter_file_created_event
        from agentmux.workflow.event_router import WorkflowEvent

        event = WorkflowEvent(kind="interruption.pane_exited", payload={"pane": "test"})
        assert filter_file_created_event(event) is None

        event = WorkflowEvent(kind="file.activity", path="some/path.txt")
        assert filter_file_created_event(event) is None

    def test_dispatch_research_task_skips_already_dispatched(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test that already dispatched tasks are not re-dispatched."""
        from agentmux.workflow.phase_helpers import dispatch_research_task

        state = {"research_tasks": {"auth": "dispatched"}}
        updates, next_phase = dispatch_research_task(
            "code-researcher", "auth", state, mock_ctx
        )

        assert updates == {}
        assert next_phase is None
        mock_ctx.runtime.spawn_task.assert_not_called()

    def test_notify_research_complete_updates_state(self, mock_ctx: MagicMock) -> None:
        """Test that research completion updates state correctly."""
        from agentmux.workflow.phase_helpers import notify_research_complete

        state = {"research_tasks": {"auth": "dispatched"}}
        updates, next_phase = notify_research_complete(
            "code-researcher", "auth", state, mock_ctx, "architect"
        )

        assert updates["research_tasks"]["auth"] == "done"
        assert next_phase is None
        mock_ctx.runtime.finish_task.assert_called_once_with("code-researcher", "auth")
        mock_ctx.runtime.notify.assert_called_once()

    def test_apply_role_preferences_calls_helpers(self, mock_ctx: MagicMock) -> None:
        """Test that apply_role_preferences calls the correct helpers."""
        from agentmux.workflow.phase_helpers import apply_role_preferences

        with (
            patch(
                "agentmux.workflow.preference_memory.proposal_artifact_for_source"
            ) as mock_proposal,
            patch(
                "agentmux.workflow.preference_memory.load_preference_proposal"
            ) as mock_load,
            patch(
                "agentmux.workflow.preference_memory.apply_preference_proposal"
            ) as mock_apply,
        ):
            mock_proposal.return_value = mock_ctx.files.pm_preference_proposal
            mock_load.return_value = None  # No proposal to apply

            apply_role_preferences(mock_ctx, "product-manager")

            mock_proposal.assert_called_once_with(mock_ctx.files, "product-manager")
            mock_load.assert_called_once_with(mock_ctx.files.pm_preference_proposal)
            mock_apply.assert_not_called()  # No proposal loaded, so no apply
