"""Tests for ImplementingHandler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from agentmux.shared.models import AgentConfig
from agentmux.workflow.event_catalog import EVENT_PLAN_WRITTEN
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import ImplementingHandler


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

            result = handler.enter(state, mock_ctx)

            mock_reset.assert_called_once()
            mock_ctx.runtime.kill_primary.assert_called_once_with("coder")
            assert "subplan_count" in result.updates
            assert result.updates["subplan_count"] == 1

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

        _, next_phase = handler.handle_event(event, state, mock_ctx)

        mock_ctx.runtime.finish_many.assert_called_once_with("coder")
        mock_ctx.runtime.deactivate.assert_called_once_with("coder")
        assert next_phase == "reviewing"

    def test_enter_single_coder_copilot_sends_fleet_prefix(
        self, mock_ctx: MagicMock
    ) -> None:
        """Test that single-coder copilot mode sends /fleet as prefix_command."""
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
            result = handler.enter(state, mock_ctx)

        assert result.updates["implementation_single_coder"] is False
