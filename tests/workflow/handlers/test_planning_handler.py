"""Tests for PlanningHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from agentmux.workflow.event_catalog import EVENT_CHANGES_REQUESTED
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PlanningHandler


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

            _, next_phase = handler.handle_event(event, empty_state, mock_ctx)

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

            _, next_phase = handler.handle_event(event, empty_state, mock_ctx)

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
