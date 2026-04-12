"""Tests for tool-event-based phase handler migration (sub-plan 3).

These tests verify that handlers correctly implement get_tool_specs() and
route MCP tool events via handle_event().
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agentmux.workflow.event_catalog import EVENT_PM_COMPLETED
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import (
    ArchitectingHandler,
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
    ctx.files.research_dir = tmp_path / "03_research"
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


# ---------------------------------------------------------------------------
# ProductManagementHandler tool-event tests
# ---------------------------------------------------------------------------


class TestProductManagementHandlerToolEvents:
    """Tests for ProductManagementHandler tool-event migration."""

    def test_get_tool_specs_returns_pm_done(self) -> None:
        """get_tool_specs() returns pm_done ToolSpec."""
        handler = ProductManagementHandler()
        specs = handler.get_tool_specs()
        spec_names = [s.name for s in specs]
        assert "pm_done" in spec_names
        pm_spec = next(s for s in specs if s.name == "pm_done")
        assert pm_spec.tool_names == ("submit_pm_done",)

    def test_get_tool_specs_returns_research_specs(self) -> None:
        """get_tool_specs() returns research ToolSpecs."""
        handler = ProductManagementHandler()
        specs = handler.get_tool_specs()
        spec_names = [s.name for s in specs]
        assert "research_code_req" in spec_names
        assert "research_web_req" in spec_names
        assert "research_done" in spec_names

    def test_get_event_specs_is_empty(self) -> None:
        """get_event_specs() returns empty sequence (all replaced by ToolSpecs)."""
        handler = ProductManagementHandler()
        assert len(handler.get_event_specs()) == 0

    def test_handle_pm_done_transitions_to_architecting(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """pm_done event transitions to architecting phase."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="pm_done",
            payload={"payload": {}},
        )

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.kill_primary.assert_called_once_with("product-manager")
        assert updates == {"last_event": EVENT_PM_COMPLETED}
        assert next_phase == "architecting"

    def test_handle_research_code_req_writes_request_then_dispatch(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_code_req writes request.md BEFORE dispatching."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_code_req",
            payload={
                "payload": {
                    "topic": "auth",
                    "context": "Need to understand auth flow",
                    "questions": ["How does OAuth work?", "What about JWT?"],
                    "scope_hints": ["src/auth/", "src/middleware/"],
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

            # Verify request.md was written
            req_path = mock_ctx.files.research_dir / "code-auth" / "request.md"
            assert req_path.exists()
            content = req_path.read_text(encoding="utf-8")
            assert "auth" in content
            assert "OAuth" in content
            assert "JWT" in content
            assert "src/auth/" in content

            # Verify dispatch happened after write
            mock_ctx.runtime.spawn_task.assert_called_once_with(
                "code-researcher", "auth", mock_ctx.files.research_dir / "code-auth"
            )
            assert "research_tasks" in updates
            assert updates["research_tasks"]["auth"] == "dispatched"
            assert next_phase is None

    def test_handle_research_code_req_idempotent(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_code_req is idempotent — does not overwrite existing request.md."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_code_req",
            payload={
                "payload": {
                    "topic": "auth",
                    "context": "original context",
                    "questions": ["original question"],
                }
            },
        )

        # Pre-create request.md
        req_dir = mock_ctx.files.research_dir / "code-auth"
        req_dir.mkdir(parents=True, exist_ok=True)
        req_path = req_dir / "request.md"
        req_path.write_text("original content", encoding="utf-8")

        with (
            patch("agentmux.workflow.prompts.write_prompt_file"),
            patch("agentmux.workflow.prompts.build_code_researcher_prompt"),
        ):
            handler.handle_event(event, empty_state, mock_ctx)

            # Content should be unchanged
            assert req_path.read_text(encoding="utf-8") == "original content"

    def test_handle_research_web_req_writes_request_then_dispatch(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_web_req writes request.md BEFORE dispatching."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_web_req",
            payload={
                "payload": {
                    "topic": "api",
                    "context": "Need to find best API practices",
                    "questions": ["What is the latest REST API standard?"],
                }
            },
        )

        with (
            patch("agentmux.workflow.prompts.write_prompt_file"),
            patch("agentmux.workflow.prompts.build_web_researcher_prompt"),
        ):
            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            req_path = mock_ctx.files.research_dir / "web-api" / "request.md"
            assert req_path.exists()
            content = req_path.read_text(encoding="utf-8")
            assert "api" in content
            assert "REST API" in content

            mock_ctx.runtime.spawn_task.assert_called_once_with(
                "web-researcher", "api", mock_ctx.files.research_dir / "web-api"
            )
            assert "web_research_tasks" in updates
            assert next_phase is None

    def test_handle_research_done_code(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_done for code type notifies product-manager."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_done",
            payload={
                "payload": {
                    "topic": "auth",
                    "role_type": "code",
                }
            },
        )

        state = {"research_tasks": {"auth": "dispatched"}}
        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_task.assert_called_once_with("code-researcher", "auth")
        mock_ctx.runtime.notify.assert_called_once()
        assert updates["research_tasks"]["auth"] == "done"
        assert next_phase is None

    def test_handle_research_done_web(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_done for web type notifies product-manager."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_done",
            payload={
                "payload": {
                    "topic": "api",
                    "role_type": "web",
                }
            },
        )

        state = {"web_research_tasks": {"api": "dispatched"}}
        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_task.assert_called_once_with("web-researcher", "api")
        mock_ctx.runtime.notify.assert_called_once()
        assert updates["web_research_tasks"]["api"] == "done"
        assert next_phase is None

    def test_handle_research_done_missing_fields(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_done with missing topic/role_type returns empty."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_done",
            payload={"payload": {"topic": ""}},
        )

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)
        assert updates == {}
        assert next_phase is None

    def test_handle_research_code_req_missing_topic(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_code_req with missing topic returns empty."""
        handler = ProductManagementHandler()
        event = WorkflowEvent(
            kind="research_code_req",
            payload={"payload": {"context": "no topic"}},
        )

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)
        assert updates == {}
        assert next_phase is None


# ---------------------------------------------------------------------------
# ArchitectingHandler tool-event tests
# ---------------------------------------------------------------------------


class TestArchitectingHandlerToolEvents:
    """Tests for ArchitectingHandler tool-event migration."""

    def test_get_tool_specs_returns_correct_specs(self) -> None:
        """get_tool_specs() returns architecture, research, and done specs."""
        handler = ArchitectingHandler()
        specs = handler.get_tool_specs()
        spec_names = [s.name for s in specs]
        assert "architecture" in spec_names
        assert "research_code_req" in spec_names
        assert "research_web_req" in spec_names
        assert "research_done" in spec_names

        arch_spec = next(s for s in specs if s.name == "architecture")
        assert arch_spec.tool_names == ("submit_architecture",)

    def test_get_event_specs_is_empty(self) -> None:
        """get_event_specs() returns empty sequence."""
        handler = ArchitectingHandler()
        assert len(handler.get_event_specs()) == 0

    def test_handle_architecture_writes_artifacts(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """architecture event reads architecture.md from disk and transitions."""
        handler = ArchitectingHandler()
        # Pre-write architecture.md (the agent writes this before calling
        # submit_architecture)
        mock_ctx.files.architecting_dir.mkdir(parents=True, exist_ok=True)
        md_path = mock_ctx.files.architecting_dir / "architecture.md"
        md_path.write_text("# Architecture\n\nSome design content.\n", encoding="utf-8")

        event = WorkflowEvent(
            kind="architecture",
            payload={"payload": {}},
        )

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        # architecture.md should still exist (handler reads, not re-creates)
        assert md_path.exists()
        # State transition
        assert next_phase == "planning"
        assert "last_event" in updates

    def test_handle_architecture_idempotent(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """architecture event is idempotent — re-running doesn't break anything."""
        handler = ArchitectingHandler()
        mock_ctx.files.architecting_dir.mkdir(parents=True, exist_ok=True)
        md_path = mock_ctx.files.architecting_dir / "architecture.md"
        md_path.write_text("# Architecture\n\nOriginal content.\n", encoding="utf-8")

        event = WorkflowEvent(kind="architecture", payload={"payload": {}})

        # First run
        handler.handle_event(event, empty_state, mock_ctx)
        first_content = md_path.read_text(encoding="utf-8")

        # Second run (reset mocks)
        mock_ctx.runtime.deactivate.reset_mock()
        mock_ctx.runtime.kill_primary.reset_mock()
        handler.handle_event(event, empty_state, mock_ctx)
        # MD content should not change
        assert md_path.read_text(encoding="utf-8") == first_content

    def test_handle_architecture_kills_architect(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """architecture event deactivates and kills the architect pane."""
        handler = ArchitectingHandler()
        mock_ctx.files.architecting_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.architecting_dir / "architecture.md").write_text(
            "# Architecture\n\nContent.\n", encoding="utf-8"
        )

        event = WorkflowEvent(kind="architecture", payload={"payload": {}})

        handler.handle_event(event, empty_state, mock_ctx)

        mock_ctx.runtime.deactivate.assert_called_once_with("architect")
        mock_ctx.runtime.kill_primary.assert_called_once_with("architect")

    def test_handle_architecture_deletes_changes_md(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """architecture event deletes changes.md if it exists."""
        handler = ArchitectingHandler()
        event = WorkflowEvent(kind="architecture", payload={"payload": {}})

        mock_ctx.files.architecting_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.architecting_dir / "architecture.md").write_text(
            "# Architecture\n\nContent.\n", encoding="utf-8"
        )
        mock_ctx.files.changes.parent.mkdir(parents=True, exist_ok=True)
        mock_ctx.files.changes.write_text("changes", encoding="utf-8")

        handler.handle_event(event, empty_state, mock_ctx)

        assert not mock_ctx.files.changes.exists()

    def test_handle_research_code_req_writes_request_then_dispatch(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_code_req writes request.md BEFORE dispatching."""
        handler = ArchitectingHandler()
        event = WorkflowEvent(
            kind="research_code_req",
            payload={
                "payload": {
                    "topic": "auth",
                    "context": "Auth context",
                    "questions": ["How does OAuth work?"],
                }
            },
        )

        with (
            patch("agentmux.workflow.prompts.write_prompt_file"),
            patch("agentmux.workflow.prompts.build_code_researcher_prompt"),
        ):
            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            req_path = mock_ctx.files.research_dir / "code-auth" / "request.md"
            assert req_path.exists()
            mock_ctx.runtime.spawn_task.assert_called_once_with(
                "code-researcher", "auth", mock_ctx.files.research_dir / "code-auth"
            )
            assert "research_tasks" in updates
            assert next_phase is None

    def test_handle_research_web_req_writes_request_then_dispatch(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_web_req writes request.md BEFORE dispatching."""
        handler = ArchitectingHandler()
        event = WorkflowEvent(
            kind="research_web_req",
            payload={
                "payload": {
                    "topic": "api",
                    "context": "API context",
                    "questions": ["What is REST?"],
                }
            },
        )

        with (
            patch("agentmux.workflow.prompts.write_prompt_file"),
            patch("agentmux.workflow.prompts.build_web_researcher_prompt"),
        ):
            updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

            req_path = mock_ctx.files.research_dir / "web-api" / "request.md"
            assert req_path.exists()
            mock_ctx.runtime.spawn_task.assert_called_once_with(
                "web-researcher", "api", mock_ctx.files.research_dir / "web-api"
            )
            assert "web_research_tasks" in updates
            assert next_phase is None

    def test_handle_research_done_code(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_done for code type notifies architect."""
        handler = ArchitectingHandler()
        event = WorkflowEvent(
            kind="research_done",
            payload={
                "payload": {
                    "topic": "auth",
                    "role_type": "code",
                }
            },
        )

        state = {"research_tasks": {"auth": "dispatched"}}
        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_task.assert_called_once_with("code-researcher", "auth")
        mock_ctx.runtime.notify.assert_called_once()
        assert updates["research_tasks"]["auth"] == "done"
        assert next_phase is None

    def test_handle_research_done_web(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """research_done for web type notifies architect."""
        handler = ArchitectingHandler()
        event = WorkflowEvent(
            kind="research_done",
            payload={
                "payload": {
                    "topic": "api",
                    "role_type": "web",
                }
            },
        )

        state = {"web_research_tasks": {"api": "dispatched"}}
        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_task.assert_called_once_with("web-researcher", "api")
        mock_ctx.runtime.notify.assert_called_once()
        assert updates["web_research_tasks"]["api"] == "done"
        assert next_phase is None


# ---------------------------------------------------------------------------
# PlanningHandler tool-event tests
# ---------------------------------------------------------------------------


class TestPlanningHandlerToolEvents:
    """Tests for PlanningHandler tool-event migration."""

    def test_get_tool_specs_returns_correct_specs(self) -> None:
        """get_tool_specs() returns plan spec (not execution_plan/subplan)."""
        handler = PlanningHandler()
        specs = handler.get_tool_specs()
        spec_names = [s.name for s in specs]
        assert "plan" in spec_names
        assert "execution_plan" not in spec_names
        assert "subplan" not in spec_names

        plan_spec = next(s for s in specs if s.name == "plan")
        assert plan_spec.tool_names == ("submit_plan",)

    def test_get_event_specs_is_empty(self) -> None:
        """get_event_specs() returns empty sequence."""
        handler = PlanningHandler()
        assert len(handler.get_event_specs()) == 0

    def test_handle_plan_writes_all_artifacts(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """plan event reads plan.yaml and materializes plan_N.md, tasks_N.md,
        execution_plan.yaml, plan.md."""
        import yaml

        handler = PlanningHandler()
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        plan_data = {
            "version": 2,
            "plan_overview": "Build core feature",
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
                    "title": "Core Setup",
                    "scope": "Set up core infrastructure",
                    "owned_files": ["src/core.py"],
                    "dependencies": "None",
                    "implementation_approach": "Implement step by step",
                    "acceptance_criteria": "Tests pass",
                    "tasks": ["Write code", "Write tests"],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": []},
            "needs_design": False,
            "needs_docs": False,
            "doc_files": [],
        }
        (mock_ctx.files.planning_dir / "plan.yaml").write_text(
            yaml.safe_dump(plan_data), encoding="utf-8"
        )

        event = WorkflowEvent(kind="plan", payload={"payload": {}})
        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        assert (mock_ctx.files.planning_dir / "plan_1.md").exists()
        assert (mock_ctx.files.planning_dir / "tasks_1.md").exists()
        assert (mock_ctx.files.planning_dir / "execution_plan.yaml").exists()
        assert (mock_ctx.files.planning_dir / "plan.md").exists()
        assert next_phase == "implementing"
        assert "last_event" in updates

    def test_handle_plan_regenerates_on_replan(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """plan event always regenerates derived artifacts (no stale files on
        replan)."""
        import yaml

        handler = PlanningHandler()
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)

        # Write stale plan_1.md from a previous plan
        stale = mock_ctx.files.planning_dir / "plan_1.md"
        stale.write_text("old content", encoding="utf-8")

        plan_data = {
            "version": 2,
            "plan_overview": "New plan",
            "groups": [
                {
                    "group_id": "g1",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "New"}],
                }
            ],
            "subplans": [
                {
                    "index": 1,
                    "title": "New Setup",
                    "scope": "New scope",
                    "owned_files": ["src/new.py"],
                    "dependencies": "None",
                    "implementation_approach": "New approach",
                    "acceptance_criteria": "All good",
                    "tasks": ["Do stuff"],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": []},
            "needs_design": False,
            "needs_docs": False,
            "doc_files": [],
        }
        (mock_ctx.files.planning_dir / "plan.yaml").write_text(
            yaml.safe_dump(plan_data), encoding="utf-8"
        )

        event = WorkflowEvent(kind="plan", payload={"payload": {}})
        handler.handle_event(event, empty_state, mock_ctx)

        assert stale.read_text(encoding="utf-8") != "old content"

    def test_handle_plan_prunes_stale_subplan_files(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """plan event removes plan_N.md / tasks_N.md for removed subplans."""
        import yaml

        handler = PlanningHandler()
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)

        # Stale files from a 2-subplan previous run
        (mock_ctx.files.planning_dir / "plan_2.md").write_text(
            "stale", encoding="utf-8"
        )
        (mock_ctx.files.planning_dir / "tasks_2.md").write_text(
            "stale", encoding="utf-8"
        )

        plan_data = {
            "version": 2,
            "plan_overview": "Single subplan",
            "groups": [
                {
                    "group_id": "g1",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "Only"}],
                }
            ],
            "subplans": [
                {
                    "index": 1,
                    "title": "Only Plan",
                    "scope": "Scope",
                    "owned_files": ["src/a.py"],
                    "dependencies": "None",
                    "implementation_approach": "Approach",
                    "acceptance_criteria": "Done",
                    "tasks": ["Task"],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": []},
            "needs_design": False,
            "needs_docs": False,
            "doc_files": [],
        }
        (mock_ctx.files.planning_dir / "plan.yaml").write_text(
            yaml.safe_dump(plan_data), encoding="utf-8"
        )

        event = WorkflowEvent(kind="plan", payload={"payload": {}})
        handler.handle_event(event, empty_state, mock_ctx)

        assert not (mock_ctx.files.planning_dir / "plan_2.md").exists()
        assert not (mock_ctx.files.planning_dir / "tasks_2.md").exists()
        assert (mock_ctx.files.planning_dir / "plan_1.md").exists()


# ---------------------------------------------------------------------------
# ImplementingHandler tool-event tests
# ---------------------------------------------------------------------------


class TestImplementingHandlerToolEvents:
    """Tests for ImplementingHandler tool-event migration."""

    def test_get_tool_specs_returns_done_spec(self) -> None:
        """get_tool_specs() returns done ToolSpec."""
        handler = ImplementingHandler()
        specs = handler.get_tool_specs()
        spec_names = [s.name for s in specs]
        assert "done" in spec_names

        done_spec = next(s for s in specs if s.name == "done")
        assert done_spec.tool_names == ("submit_done",)

    def test_get_event_specs_is_empty(self) -> None:
        """get_event_specs() returns empty sequence."""
        handler = ImplementingHandler()
        assert len(handler.get_event_specs()) == 0

    def test_handle_done_writes_done_marker_and_transitions(
        self, mock_ctx: MagicMock
    ) -> None:
        """done event writes done_N marker and transitions correctly."""
        handler = ImplementingHandler()
        event = WorkflowEvent(
            kind="done",
            payload={
                "payload": {
                    "subplan_index": 1,
                }
            },
        )

        # Setup state for single subplan
        state = {
            "implementation_group_index": 1,
            "implementation_group_mode": "serial",
            "implementation_active_plan_ids": ["plan_1"],
        }

        # Create execution plan
        mock_ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        import yaml

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

        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        # Verify done_N marker was written
        done_n_path = mock_ctx.files.implementation_dir / "done_1"
        assert done_n_path.exists()

        mock_ctx.runtime.hide_task.assert_called_once_with("coder", 1)
        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"

    def test_handle_done_idempotent(self, mock_ctx: MagicMock) -> None:
        """done event is idempotent — doesn't overwrite existing done_N marker."""
        handler = ImplementingHandler()
        event = WorkflowEvent(
            kind="done",
            payload={
                "payload": {
                    "subplan_index": 1,
                }
            },
        )

        state = {
            "implementation_group_index": 1,
            "implementation_group_mode": "serial",
            "implementation_active_plan_ids": ["plan_1"],
        }

        import yaml

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

        # Pre-create done_1 marker
        done_path = mock_ctx.files.implementation_dir / "done_1"
        done_path.touch()

        handler.handle_event(event, state, mock_ctx)
        assert done_path.exists()


# ---------------------------------------------------------------------------
# ReviewingHandler tool-event tests
# ---------------------------------------------------------------------------


class TestReviewingHandlerToolEvents:
    """Tests for ReviewingHandler tool-event migration."""

    def test_get_tool_specs_returns_review_spec(self) -> None:
        """get_tool_specs() returns review ToolSpec."""
        handler = ReviewingHandler()
        specs = handler.get_tool_specs()
        spec_names = [s.name for s in specs]
        assert "review" in spec_names

        review_spec = next(s for s in specs if s.name == "review")
        assert review_spec.tool_names == ("submit_review",)

    def test_get_event_specs_keeps_summary_ready(self) -> None:
        """get_event_specs() keeps summary_ready EventSpec."""
        handler = ReviewingHandler()
        specs = handler.get_event_specs()
        spec_names = [s.name for s in specs]
        assert "summary_ready" in spec_names
        # review_ready should be removed (replaced by ToolSpec)
        assert "review_ready" not in spec_names

    def test_handle_review_verdict_pass(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """review event with verdict:pass reads review.yaml and requests summary."""
        from agentmux.workflow.event_catalog import EVENT_REVIEW_PASSED

        handler = ReviewingHandler()
        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (mock_ctx.files.review_dir / "review.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "pass",
                    "summary": "Looks good!",
                    "findings": [],
                    "commit_message": "feat: implement feature",
                },
                default_flow_style=False,
            )
        )
        event = WorkflowEvent(kind="review", payload={"payload": {}})

        updates, next_phase = handler.handle_event(event, empty_state, mock_ctx)

        yaml_path = mock_ctx.files.review_dir / "review.yaml"
        md_path = mock_ctx.files.review_dir / "review.md"
        assert yaml_path.exists()
        assert md_path.exists()

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.kill_primary.assert_called_once_with("coder")
        assert updates.get("awaiting_summary") is True
        assert updates.get("last_event") == EVENT_REVIEW_PASSED
        assert next_phase is None

    def test_handle_review_verdict_fail_under_max(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """review event with verdict:fail transitions to fixing."""
        from agentmux.workflow.event_catalog import EVENT_REVIEW_FAILED

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

        yaml_path = mock_ctx.files.review_dir / "review.yaml"
        md_path = mock_ctx.files.review_dir / "review.md"
        assert yaml_path.exists()
        assert md_path.exists()
        assert mock_ctx.files.fix_request.exists()

        assert updates["review_iteration"] == 1
        assert updates["last_event"] == EVENT_REVIEW_FAILED
        assert next_phase == "fixing"

    def test_handle_review_verdict_fail_at_max(self, mock_ctx: MagicMock) -> None:
        """verdict:fail at max iterations transitions to completing."""
        from agentmux.workflow.event_catalog import EVENT_REVIEW_FAILED

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

        state = {"review_iteration": 3}
        updates, next_phase = handler.handle_event(event, state, mock_ctx)

        assert next_phase == "completing"
        assert updates["last_event"] == EVENT_REVIEW_FAILED

    def test_handle_review_idempotent(
        self, mock_ctx: MagicMock, empty_state: dict
    ) -> None:
        """review.yaml is agent-written; handler only reads it, never overwrites."""
        handler = ReviewingHandler()

        mock_ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = mock_ctx.files.review_dir / "review.yaml"
        yaml_path.write_text("original: content", encoding="utf-8")
        md_path = mock_ctx.files.review_dir / "review.md"
        md_path.write_text("# Review\n\nLooks good!", encoding="utf-8")

        event = WorkflowEvent(kind="review", payload={"payload": {}})
        handler.handle_event(event, empty_state, mock_ctx)
        assert yaml_path.read_text(encoding="utf-8") == "original: content"
