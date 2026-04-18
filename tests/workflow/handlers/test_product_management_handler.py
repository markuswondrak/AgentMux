"""Tests for ProductManagementHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agentmux.workflow.event_catalog import EVENT_PM_COMPLETED
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import ProductManagementHandler


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

            result = handler.enter(empty_state, mock_ctx)

            mock_build.assert_called_once_with(mock_ctx.files, None)
            mock_write.assert_called_once()
            mock_send.assert_called_once_with(
                mock_ctx, "product-manager", Path("/mock/prompt.md")
            )
            assert result.updates == {}

    def test_handle_pm_completed(self, mock_ctx: MagicMock, empty_state: dict) -> None:
        """Test handling of pm_done tool call."""
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
