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
import yaml

from agentmux.workflow.event_catalog import (
    EVENT_CHANGES_REQUESTED,
    EVENT_PLAN_WRITTEN,
    EVENT_PM_COMPLETED,
    EVENT_REVIEW_PASSED,
)
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
    pass


@pytest.fixture
def mock_ctx(tmp_path: Path) -> MagicMock:
    """Create a mock PipelineContext with realistic file structure."""
    ctx = MagicMock()
    ctx.files.feature_dir = tmp_path
    ctx.files.product_management_dir = tmp_path / "01_product_management"
    ctx.files.architecting_dir = tmp_path / "02_architecting"
    ctx.files.planning_dir = tmp_path / "04_planning"
    ctx.files.design_dir = tmp_path / "05_design"
    ctx.files.implementation_dir = tmp_path / "06_implementation"
    ctx.files.review_dir = tmp_path / "07_review"
    ctx.files.completion_dir = tmp_path / "08_completion"
    ctx.files.research_dir = tmp_path / "research"
    ctx.files.changes = tmp_path / "08_completion" / "changes.md"
    ctx.files.plan = tmp_path / "04_planning" / "plan.md"
    ctx.files.tasks = tmp_path / "04_planning" / "tasks.md"
    ctx.files.design = tmp_path / "05_design" / "design.md"
    ctx.files.review = tmp_path / "07_review" / "review.md"
    ctx.files.fix_request = tmp_path / "07_review" / "fix_request.txt"
    ctx.files.requirements = tmp_path / "requirements.md"
    ctx.files.context = tmp_path / "context.md"
    ctx.files.architecture = tmp_path / "02_architecting" / "architecture.md"
    ctx.files.project_dir = tmp_path.parent
    ctx.files.relative_path = lambda p: str(p.relative_to(tmp_path))
    ctx.files.state = tmp_path / "state.json"
    ctx.agents = {}
    ctx.max_review_iterations = 3
    ctx.workflow_settings.completion.skip_final_approval = False
    ctx.github_config.branch_prefix = "feature/"

    # Create required files for prompts that include them
    ctx.files.context.write_text("# Context")
    ctx.files.architecture.parent.mkdir(parents=True, exist_ok=True)
    ctx.files.architecture.write_text("# Architecture")
    (tmp_path / "requirements.md").write_text("# Requirements")
    ctx.files.plan.parent.mkdir(parents=True, exist_ok=True)
    ctx.files.plan.write_text("# Plan")

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

            mock_build.assert_called_once_with(mock_ctx.files, None)
            mock_write.assert_called_once()
            mock_send.assert_called_once_with(
                mock_ctx, "product-manager", Path("/mock/prompt.md")
            )
            assert updates == {}

    def test_handle_pm_completed(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test handling of pm_done marker."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(kind="pm_done", payload={"payload": {}})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.kill_primary.assert_called_once_with("product-manager")
        assert updates == {"last_event": EVENT_PM_COMPLETED}
        assert next_phase == "architecting"

    def test_handle_code_research_request(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test dispatching code-researcher task."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_code_req",
            payload={
                "payload": {
                    "topic": "auth",
                    "context": "Need to understand auth flow",
                    "questions": ["How does auth work?"],
                    "scope_hints": ["src/auth/"],
                }
            },
        )

        with (
            patch("agentmux.workflow.prompts.write_prompt_file") as mock_write,
            patch(
                "agentmux.workflow.prompts.build_code_researcher_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "research prompt"

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            research_dir = mock_ctx.files.research_dir / "code-auth"
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
            kind="research_web_req",
            payload={
                "payload": {
                    "topic": "api",
                    "context": "Need to understand API design",
                    "questions": ["What are best practices?"],
                    "scope_hints": [],
                }
            },
        )

        with (
            patch("agentmux.workflow.prompts.write_prompt_file") as mock_write,
            patch(
                "agentmux.workflow.prompts.build_web_researcher_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "research prompt"

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            research_dir = mock_ctx.files.research_dir / "web-api"
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
        event = WorkflowEvent(
            kind="research_done",
            payload={"payload": {"topic": "auth", "role_type": "code"}},
        )

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
            kind="research_code_req",
            payload={
                "payload": {
                    "topic": "auth",
                    "context": "Need to understand auth",
                    "questions": ["How does auth work?"],
                    "scope_hints": [],
                }
            },
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

    def test_enter_sends_planner_prompt(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends planner prompt."""
        handler = PlanningHandler()

        with (
            patch(
                "agentmux.workflow.handlers.planning.write_prompt_file"
            ) as mock_write,
            patch("agentmux.workflow.handlers.planning.send_to_role") as mock_send,
            patch(
                "agentmux.workflow.handlers.planning.build_planner_prompt"
            ) as mock_build,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "planner prompt"

            handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files, None)
            mock_send.assert_called_once_with(
                mock_ctx, "planner", Path("/mock/prompt.md")
            )

    def test_enter_sends_change_prompt_on_replan(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that enter() sends change prompt when replanning."""
        handler = PlanningHandler()
        state = {"last_event": EVENT_CHANGES_REQUESTED}

        # Create changes.md to trigger replan mode
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.changes.parent.mkdir(parents=True, exist_ok=True)
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

            handler.enter(state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files, None)
            mock_send.assert_called_once_with(
                mock_ctx, "planner", Path("/mock/prompt.md")
            )

    def test_handle_plan_written_all_files_exist(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        handler = PlanningHandler()
        event = WorkflowEvent(kind="plan", payload={"payload": {}})

        # Write plan.yaml (version 2)
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        plan_data = {
            "version": 2,
            "plan_overview": "# Plan\n\nTest.",
            "groups": [
                {
                    "group_id": "g1",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "Setup"}],
                }
            ],
            "subplans": [
                {
                    "index": 1,
                    "title": "Setup",
                    "scope": "Core setup",
                    "owned_files": ["src/setup.py"],
                    "dependencies": "None",
                    "implementation_approach": "Setup",
                    "acceptance_criteria": "Done",
                    "tasks": ["Setup task"],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": []},
            "needs_design": False,
            "needs_docs": False,
            "doc_files": [],
        }
        (mock_ctx.files.planning_dir / "plan.yaml").write_text(
            yaml.dump(plan_data, default_flow_style=False)
        )

        with (
            patch("agentmux.workflow.handlers.planning.load_execution_plan"),
            patch("agentmux.workflow.handlers.planning.load_plan_meta") as mock_meta,
        ):
            mock_meta.return_value = {"needs_design": False}

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            assert next_phase == "implementing"
            mock_ctx.runtime.kill_primary("planner")

    def test_handle_plan_written_needs_design(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to designing when needs_design is true."""
        handler = PlanningHandler()
        event = WorkflowEvent(kind="plan", payload={"payload": {}})

        # Write plan.yaml (version 2)
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        plan_data = {
            "version": 2,
            "plan_overview": "# Plan\n\nTest.",
            "groups": [
                {
                    "group_id": "g1",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "Setup"}],
                }
            ],
            "subplans": [
                {
                    "index": 1,
                    "title": "Setup",
                    "scope": "Core setup",
                    "owned_files": ["src/setup.py"],
                    "dependencies": "None",
                    "implementation_approach": "Setup",
                    "acceptance_criteria": "Done",
                    "tasks": ["Setup task"],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": []},
            "needs_design": True,
            "needs_docs": False,
            "doc_files": [],
        }
        (mock_ctx.files.planning_dir / "plan.yaml").write_text(
            yaml.dump(plan_data, default_flow_style=False)
        )

        # Add designer to agents
        mock_ctx.agents = {"designer": MagicMock()}

        with (
            patch("agentmux.workflow.handlers.planning.load_execution_plan"),
            patch("agentmux.workflow.handlers.planning.load_plan_meta") as mock_meta,
        ):
            mock_meta.return_value = {"needs_design": True}

            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            assert next_phase == "designing"

    def test_deletes_changes_md_on_transition(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test that changes.md is deleted on plan submission."""
        handler = PlanningHandler()
        event = WorkflowEvent(kind="plan", payload={"payload": {}})

        # Write plan.yaml (version 2) and changes.md
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.changes.parent.mkdir(parents=True, exist_ok=True)
        plan_data = {
            "version": 2,
            "plan_overview": "# Plan\n\nTest.",
            "groups": [
                {
                    "group_id": "g1",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "Setup"}],
                }
            ],
            "subplans": [
                {
                    "index": 1,
                    "title": "Setup",
                    "scope": "Core setup",
                    "owned_files": ["src/setup.py"],
                    "dependencies": "None",
                    "implementation_approach": "Setup",
                    "acceptance_criteria": "Done",
                    "tasks": ["Setup task"],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": []},
            "needs_design": False,
            "needs_docs": False,
            "doc_files": [],
        }
        (mock_ctx.files.planning_dir / "plan.yaml").write_text(
            yaml.dump(plan_data, default_flow_style=False)
        )
        mock_ctx.files.changes.write_text("changes")

        with (
            patch("agentmux.workflow.handlers.planning.load_execution_plan"),
            patch("agentmux.workflow.handlers.planning.load_plan_meta") as mock_meta,
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

            handler.enter(empty_state, mock_ctx)

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
        event = WorkflowEvent(kind="design_written", path="05_design/design.md")

        # Create the design file so is_ready predicate passes
        mock_ctx.files.design.parent.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.design.write_text("design")

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.deactivate.assert_called_once_with("designer")
        assert next_phase == "implementing"


class TestImplementingHandler:
    """Tests for ImplementingHandler."""

    @staticmethod
    def _write_execution_plan(
        mock_ctx: MagicMock, groups: list[dict[str, object]]
    ) -> None:
        """Create an execution plan and matching plan files for tests."""
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump({"groups": groups}, default_flow_style=False)
        )

        plan_files = {
            plan["file"]
            for group in groups
            for plan in group["plans"]
            if isinstance(plan, dict) and "file" in plan
        }
        for plan_file in plan_files:
            (mock_ctx.files.planning_dir / str(plan_file)).write_text(str(plan_file))

    def test_enter_resets_markers_and_dispatches(self, mock_ctx: MagicMock) -> None:
        """Test that enter() resets markers and dispatches first group."""
        handler = ImplementingHandler()
        state = {"last_event": EVENT_PLAN_WRITTEN}

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(
                {
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "First Plan"}],
                        }
                    ],
                },
                default_flow_style=False,
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
        event = WorkflowEvent(kind="done", payload={"payload": {"subplan_index": 1}})

        # Pre-create done_1 so group-completion check sees it as already done
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.implementation_dir / "done_1").touch()

        # Setup state for parallel group
        state = {
            "implementation_group_index": 1,
            "implementation_group_mode": "parallel",
            "implementation_active_plan_ids": ["plan_1", "plan_2"],
        }

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(
                {
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
                },
                default_flow_style=False,
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        (mock_ctx.files.planning_dir / "plan_2.md").write_text("plan 2")

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.hide_task.assert_called_once_with("coder", 1)
        assert "completed_subplans" in updates
        assert 1 in updates["completed_subplans"]
        assert next_phase is None  # Not all subplans complete yet

    def test_handle_implementation_completed(self, mock_ctx: MagicMock) -> None:
        """Test transition when all implementation is complete."""
        handler = ImplementingHandler()
        event = WorkflowEvent(kind="done", payload={"payload": {"subplan_index": 1}})

        # Setup state with all markers complete
        state = {
            "implementation_group_index": 1,
            "implementation_group_mode": "serial",
            "implementation_active_plan_ids": ["plan_1"],
        }

        # Create execution plan and done marker
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(
                {
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                        }
                    ],
                },
                default_flow_style=False,
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.implementation_dir / "done_1").write_text("")

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"

    def test_enter_single_coder_copilot_sends_fleet_prefix(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test that single-coder copilot mode sends /fleet as prefix_command."""
        from agentmux.shared.models import AgentConfig

        handler = ImplementingHandler()
        state = {"last_event": EVENT_PLAN_WRITTEN}

        # Configure coder as copilot with single_coder
        mock_ctx.agents = {
            "coder": AgentConfig(
                role="coder",
                cli="copilot",
                model="claude-sonnet-4.6",
                provider="copilot",
                single_coder=True,
            )
        }

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(
                {
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                        }
                    ],
                },
                default_flow_style=False,
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch("agentmux.workflow.handlers.implementing.reset_markers"),
            patch(
                "agentmux.workflow.handlers.implementing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.implementing.build_coder_whole_plan_prompt"
            ) as mock_build,
            patch("agentmux.workflow.handlers.implementing.send_to_role") as mock_send,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "coder whole plan prompt"

            handler.enter(state, mock_ctx)

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs.get("prefix_command") == "/fleet"

    def test_enter_single_coder_non_copilot_no_fleet_prefix(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test that single-coder non-copilot mode does NOT send /fleet prefix."""
        from agentmux.shared.models import AgentConfig

        handler = ImplementingHandler()
        state = {"last_event": EVENT_PLAN_WRITTEN}

        # Configure coder as non-copilot with single_coder
        mock_ctx.agents = {
            "coder": AgentConfig(
                role="coder",
                cli="some-cli",
                model="some-model",
                provider="some-provider",
                single_coder=True,
            )
        }

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(
                {
                    "groups": [
                        {
                            "group_id": "group1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                        }
                    ],
                },
                default_flow_style=False,
            )
        )
        (mock_ctx.files.planning_dir / "plan_1.md").write_text("plan 1")
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)

        with (
            patch("agentmux.workflow.handlers.implementing.reset_markers"),
            patch(
                "agentmux.workflow.handlers.implementing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.implementing.build_coder_whole_plan_prompt"
            ) as mock_build,
            patch("agentmux.workflow.handlers.implementing.send_to_role") as mock_send,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build.return_value = "coder whole plan prompt"

            handler.enter(state, mock_ctx)

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs.get("prefix_command") is None

    def test_enter_resume_uses_state_single_coder_true(
        self, mock_ctx: MagicMock
    ) -> None:
        """Resume should dispatch the whole plan when persisted single-coder is true."""
        handler = ImplementingHandler()
        state = {
            "last_event": "implementation_resumed",
            "implementation_single_coder": True,
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with (
            patch.object(handler, "_dispatch_whole_plan") as mock_whole,
            patch.object(handler, "_dispatch_active_group") as mock_group,
        ):
            handler.enter(state, mock_ctx)

        mock_whole.assert_called_once()
        mock_group.assert_not_called()

    def test_enter_fresh_start_logs_group_and_single_coder_mode(
        self, mock_ctx: MagicMock
    ) -> None:
        """Fresh starts should log the authoritative group and single-coder modes."""
        from agentmux.shared.models import AgentConfig

        handler = ImplementingHandler()
        state = {"last_event": EVENT_PLAN_WRITTEN}
        mock_ctx.agents = {
            "coder": AgentConfig(
                role="coder",
                cli="some-cli",
                model="some-model",
                provider="some-provider",
                single_coder=False,
            )
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with (
            patch("builtins.print") as mock_print,
            patch.object(handler, "_dispatch_active_group"),
        ):
            handler.enter(state, mock_ctx)

        mock_print.assert_called_once_with(
            "Starting implementing phase "
            "(fresh start, group_mode=serial, single_coder=False)."
        )

    def test_enter_resume_logs_authoritative_group_and_single_coder_mode(
        self, mock_ctx: MagicMock
    ) -> None:
        """Resume should log the active group mode alongside single-coder mode."""
        handler = ImplementingHandler()
        state = {
            "last_event": "implementation_resumed",
            "implementation_single_coder": True,
            "implementation_group_mode": "parallel",
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with (
            patch("builtins.print") as mock_print,
            patch.object(handler, "_dispatch_whole_plan"),
        ):
            handler.enter(state, mock_ctx)

        mock_print.assert_called_once_with(
            "Resuming implementing phase "
            "(group_mode=serial, single_coder=True, source=saved state)."
        )

    def test_enter_resume_logs_none_group_mode_when_no_active_group(
        self, mock_ctx: MagicMock
    ) -> None:
        """Resume should log group_mode=none when all implementation groups are done."""
        handler = ImplementingHandler()
        state = {
            "last_event": "implementation_resumed",
            "implementation_single_coder": False,
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.implementation_dir / "done_1").write_text("")
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with patch("builtins.print") as mock_print:
            handler.enter(state, mock_ctx)

        mock_print.assert_called_once_with(
            "Resuming implementing phase "
            "(group_mode=none, single_coder=False, source=saved state)."
        )

    def test_enter_resume_uses_state_single_coder_false(
        self, mock_ctx: MagicMock
    ) -> None:
        """Resume should dispatch the active group when persisted mode is false."""
        from agentmux.shared.models import AgentConfig

        handler = ImplementingHandler()
        state = {
            "last_event": "implementation_resumed",
            "implementation_single_coder": False,
        }
        mock_ctx.agents = {
            "coder": AgentConfig(
                role="coder",
                cli="copilot",
                model="claude-sonnet-4.6",
                provider="copilot",
                single_coder=True,
            )
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with (
            patch.object(handler, "_dispatch_whole_plan") as mock_whole,
            patch.object(handler, "_dispatch_active_group") as mock_group,
        ):
            handler.enter(state, mock_ctx)

        mock_whole.assert_not_called()
        mock_group.assert_called_once()

    def test_enter_resume_missing_single_coder_uses_agent_config(
        self, mock_ctx: MagicMock
    ) -> None:
        """Resume should fall back to the current coder config when state is missing."""
        from agentmux.shared.models import AgentConfig

        handler = ImplementingHandler()
        state = {"last_event": "implementation_resumed"}
        mock_ctx.agents = {
            "coder": AgentConfig(
                role="coder",
                cli="copilot",
                model="claude-sonnet-4.6",
                provider="copilot",
                single_coder=True,
            )
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with (
            patch.object(handler, "_dispatch_whole_plan") as mock_whole,
            patch.object(handler, "_dispatch_active_group") as mock_group,
        ):
            handler.enter(state, mock_ctx)

        mock_whole.assert_called_once()
        mock_group.assert_not_called()

    def test_dispatch_active_group_prefers_persisted_parallel_mode(
        self, mock_ctx: MagicMock
    ) -> None:
        """Dispatch should use persisted group mode over the schedule when resuming."""
        handler = ImplementingHandler()
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        schedule = [
            {
                "group_id": "group1",
                "mode": "serial",
                "plan_paths": [
                    mock_ctx.files.planning_dir / "plan_1.md",
                    mock_ctx.files.planning_dir / "plan_2.md",
                ],
                "plan_ids": ["plan_1", "plan_2"],
                "plan_names": ["Plan 1", "Plan 2"],
                "marker_indexes": [1, 2],
            }
        ]
        state = {"implementation_group_mode": "parallel"}

        with (
            patch(
                "agentmux.workflow.handlers.implementing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.implementing.build_coder_subplan_prompt"
            ) as mock_build,
            patch("agentmux.workflow.handlers.implementing.send_to_role") as mock_send,
        ):
            mock_write.side_effect = [
                Path("/mock/prompt-1.md"),
                Path("/mock/prompt-2.md"),
            ]
            mock_build.return_value = "coder prompt"

            handler._dispatch_active_group(
                mock_ctx, schedule, active_group_index=0, state=state
            )

        mock_ctx.runtime.send_many.assert_called_once()
        mock_send.assert_not_called()

    def test_enter_fresh_start_persists_agent_single_coder(
        self, mock_ctx: MagicMock
    ) -> None:
        """Fresh starts should persist the current coder single-coder setting."""
        from agentmux.shared.models import AgentConfig

        handler = ImplementingHandler()
        state = {"last_event": EVENT_PLAN_WRITTEN}
        mock_ctx.agents = {
            "coder": AgentConfig(
                role="coder",
                cli="some-cli",
                model="some-model",
                provider="some-provider",
                single_coder=False,
            )
        }
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        self._write_execution_plan(
            mock_ctx,
            [
                {
                    "group_id": "group1",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Plan 1"}],
                }
            ],
        )

        with patch.object(handler, "_dispatch_active_group"):
            updates = handler.enter(state, mock_ctx)

        assert updates["implementation_single_coder"] is False


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
                "agentmux.workflow.handlers.reviewing.build_reviewer_logic_prompt"
            ) as mock_build_logic,
            patch(
                "agentmux.workflow.handlers.reviewing.role_display_label"
            ) as mock_label,
        ):
            mock_write.return_value = Path("/mock/prompt.md")
            mock_build_logic.return_value = "reviewer logic prompt"
            mock_label.return_value = "[reviewer] iteration 1"

            handler.enter(empty_state, mock_ctx)

            mock_build_logic.assert_called_once()
            mock_send.assert_called_once()

    def test_handle_review_passed(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test that VERDICT:PASS stays in reviewing and requests summary."""
        handler = ReviewingHandler()

        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / "review.yaml").write_text(
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
        event = WorkflowEvent(kind="review", payload={"payload": {}})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.kill_primary.assert_called_once_with("coder")
        # Stays in reviewing, awaiting summary
        assert next_phase is None
        assert updates.get("awaiting_summary") is True
        assert updates.get("last_event") == EVENT_REVIEW_PASSED

    def test_handle_review_yaml_pass_materializes_review_md(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Review tool event writes both review.yaml and review.md."""
        handler = ReviewingHandler()

        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / "review.yaml").write_text(
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
        event = WorkflowEvent(kind="review", payload={"payload": {}})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert next_phase is None
        assert updates.get("awaiting_summary") is True
        yaml_path = mock_ctx.files.review_dir / "review.yaml"
        assert yaml_path.exists()
        assert mock_ctx.files.review.exists()
        assert mock_ctx.files.review.read_text(encoding="utf-8").startswith(
            "verdict: pass"
        )

    def test_handle_review_failed_under_max_iterations(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to fixing when under max iterations."""
        handler = ReviewingHandler()

        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / "review.yaml").write_text(
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
        event = WorkflowEvent(kind="review", payload={"payload": {}})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert next_phase == "fixing"
        assert updates["review_iteration"] == 1
        assert mock_ctx.files.fix_request.exists()

    def test_handle_review_yaml_fail_creates_fix_request(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Review tool event with fail verdict creates fix_request.txt."""
        handler = ReviewingHandler()

        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / "review.yaml").write_text(
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
        event = WorkflowEvent(kind="review", payload={"payload": {}})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert next_phase == "fixing"
        assert updates["review_iteration"] == 1
        assert mock_ctx.files.fix_request.exists()
        assert mock_ctx.files.fix_request.read_text(encoding="utf-8").startswith(
            "verdict: fail"
        )

    def test_handle_review_failed_at_max_iterations(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """Test transition to completing when max iterations reached."""
        handler = ReviewingHandler()

        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / "review.yaml").write_text(
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
        event = WorkflowEvent(kind="review", payload={"payload": {}})

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

            handler.enter(empty_state, mock_ctx)

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
        event = WorkflowEvent(kind="done", path="06_implementation/done_1")

        # Create the done marker so is_ready predicate passes
        mock_ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.implementation_dir / "done_1").touch()

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"


class TestCompletingHandler:
    """Tests for CompletingHandler."""

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
            kind="research_code_req",
            payload={
                "payload": {
                    "topic": "auth",
                    "context": "Need to understand auth",
                    "questions": ["How does auth work?"],
                    "scope_hints": [],
                }
            },
        )

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
