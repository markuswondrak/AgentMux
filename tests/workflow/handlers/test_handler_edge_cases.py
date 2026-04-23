"""Edge case tests for handlers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PlanningHandler, ProductManagementHandler


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
