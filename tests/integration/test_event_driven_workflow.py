"""Integration test for event-driven workflow.

This test simulates a complete workflow using file events to verify
the event-driven architecture works end-to-end.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import AgentConfig, GitHubConfig, WorkflowSettings
from agentmux.workflow.event_router import WorkflowEvent, WorkflowEventRouter
from agentmux.workflow.handlers import PHASE_HANDLERS
from agentmux.workflow.transitions import PipelineContext


class FakeRuntime:
    """Mock runtime for testing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.notifications: list[tuple[str, str]] = []

    def send(
        self,
        role: str,
        prompt_file: Path,
        display_label: str | None = None,
        prefix_command: str | None = None,
    ) -> None:
        self.calls.append(
            ("send", role, prompt_file.name, display_label, prefix_command)
        )

    def send_many(self, role: str, prompt_specs: list[object]) -> None:
        self.calls.append(("send_many", role, len(prompt_specs)))

    def spawn_task(self, role: str, task_id: str, research_dir: Path) -> None:
        self.calls.append(("spawn_task", role, task_id, research_dir.name))

    def finish_task(self, role: str, task_id: str) -> None:
        self.calls.append(("finish_task", role, task_id))

    def hide_task(self, role: str, task_id: int | str) -> None:
        self.calls.append(("hide_task", role, str(task_id)))

    def deactivate(self, role: str) -> None:
        self.calls.append(("deactivate", role))

    def deactivate_many(self, roles: tuple[str, ...]) -> None:
        self.calls.append(("deactivate_many", roles))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def notify(self, role: str, text: str) -> None:
        self.notifications.append((role, text))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))

    def show_completion_ui(self, feature_dir: Path) -> None:
        self.calls.append(("show_completion_ui", str(feature_dir)))


class TestEventDrivenWorkflowIntegration(unittest.TestCase):
    """Integration test simulating complete workflow with events."""

    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        """Create pipeline context and state path."""
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(
            project_dir, feature_dir, "integration test feature", "session-x"
        )

        # Create required initial files
        files.plan.parent.mkdir(parents=True, exist_ok=True)
        files.plan.write_text("# Plan\n", encoding="utf-8")
        files.tasks.parent.mkdir(parents=True, exist_ok=True)
        files.tasks.write_text("# Tasks\n", encoding="utf-8")
        files.architecture.write_text("# Architecture\n", encoding="utf-8")

        agents = {
            "planner": AgentConfig(role="planner", cli="claude", model="opus", args=[]),
            "coder": AgentConfig(
                role="coder", cli="codex", model="gpt-5.3-codex", args=[]
            ),
            "reviewer": AgentConfig(
                role="reviewer", cli="claude", model="sonnet", args=[]
            ),
        }

        ctx = PipelineContext(
            files=files,
            runtime=FakeRuntime(),
            agents=agents,
            max_review_iterations=3,
            prompts={},
            github_config=GitHubConfig(),
            workflow_settings=WorkflowSettings(),
        )
        return ctx, files.state

    def _write_execution_plan(self, ctx: PipelineContext) -> None:
        """Write a simple execution plan."""
        planning_dir = ctx.files.planning_dir
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / "plan_1.md").write_text(
            "## Sub-plan 1: implementation\n", encoding="utf-8"
        )
        (planning_dir / "tasks_1.md").write_text(
            "# Tasks for plan 1\n\n- [ ] task\n", encoding="utf-8"
        )
        (planning_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "group_id": "g1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "implementation"}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_full_workflow_with_events(self):
        """Simulate a complete workflow using file events."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            # Create router
            router = WorkflowEventRouter(PHASE_HANDLERS)

            # 1. Start in product_management phase
            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)

            # Write the done marker that the event represents
            pm_dir = feature_dir / "01_product_management"
            pm_dir.mkdir(parents=True, exist_ok=True)
            (pm_dir / "done").touch()

            event = WorkflowEvent(
                kind="file.created", path="01_product_management/done"
            )
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify transition to architecting
            state = load_state(state_path)
            self.assertEqual("architecting", state["phase"])
            self.assertEqual("pm_completed", state["last_event"])

            # 2. Create architecture.md to trigger transition to planning
            ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
            ctx.files.architecture.write_text("# Test Architecture\n", encoding="utf-8")

            event = WorkflowEvent(
                kind="file.created", path="02_planning/architecture.md"
            )
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify transition to planning
            state = load_state(state_path)
            self.assertEqual("planning", state["phase"])
            self.assertEqual("architecture_written", state["last_event"])

            # 3. Create plan files to trigger transition to implementing
            ctx.files.plan.write_text("# Test Plan\n", encoding="utf-8")
            ctx.files.tasks.write_text("# Tasks\n- [ ] task\n", encoding="utf-8")
            (ctx.files.planning_dir / "plan_meta.json").write_text(
                json.dumps({"needs_design": False}), encoding="utf-8"
            )
            self._write_execution_plan(ctx)

            # Handle plan creation
            event = WorkflowEvent(kind="file.created", path="02_planning/plan.md")
            router.handle(event, load_state(state_path), ctx)

            event = WorkflowEvent(kind="file.created", path="02_planning/tasks.md")
            router.handle(event, load_state(state_path), ctx)

            event = WorkflowEvent(
                kind="file.created", path="02_planning/plan_meta.json"
            )
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify transition to implementing
            state = load_state(state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertEqual("plan_written", state["last_event"])

            # 4. Create done marker to trigger transition to reviewing
            ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.implementation_dir / "done_1").touch()

            event = WorkflowEvent(kind="file.created", path="05_implementation/done_1")
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify transition to reviewing
            state = load_state(state_path)
            self.assertEqual("reviewing", state["phase"])
            self.assertEqual("implementation_completed", state["last_event"])

            # 5. Create review.md with pass verdict — reviewer asked for summary
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: pass\n", encoding="utf-8")

            event = WorkflowEvent(kind="file.created", path="06_review/review.md")
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Still in reviewing, awaiting summary from reviewer
            state = load_state(state_path)
            self.assertEqual("reviewing", state["phase"])
            self.assertTrue(state.get("awaiting_summary"))

            # 5b. Reviewer writes summary — kill reviewer + transition to completing
            ctx.files.summary.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.summary.write_text(
                "## Summary\nImplemented the feature.\n", encoding="utf-8"
            )

            event = WorkflowEvent(kind="file.created", path="08_completion/summary.md")
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify transition to completing
            state = load_state(state_path)
            self.assertEqual("completing", state["phase"])
            self.assertEqual("review_passed", state["last_event"])

            # 6. Create approval.json to trigger completion
            ctx.files.completion_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.completion_dir / "approval.json").write_text(
                json.dumps({"action": "approve", "exclude_files": []}), encoding="utf-8"
            )

            # Mock the completion service to avoid git operations
            with patch(
                "agentmux.workflow.handlers.completing.CompletionService.finalize_approval"
            ) as mock_finalize:
                mock_finalize.return_value = MagicMock(
                    commit_hash="abc123",
                    pr_url=None,
                    cleaned_up=True,
                )

                event = WorkflowEvent(
                    kind="file.created", path="08_completion/approval.json"
                )
                updates, exit_code = router.handle(event, load_state(state_path), ctx)

            # Verify exit success - router returns exit_code separately
            self.assertEqual(0, exit_code)

    def test_workflow_handles_research_tasks(self):
        """Test that research tasks are properly dispatched and completed."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            router = WorkflowEventRouter(PHASE_HANDLERS)

            # Start in planning phase
            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)

            # Create research request
            research_dir = ctx.files.research_dir / "code-auth"
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "request.md").write_text("research auth", encoding="utf-8")

            # Handle research request
            event = WorkflowEvent(
                kind="file.created", path="03_research/code-auth/request.md"
            )

            with (
                patch("agentmux.workflow.prompts.write_prompt_file") as mock_write,
                patch(
                    "agentmux.workflow.prompts.build_code_researcher_prompt"
                ) as mock_build,
            ):
                mock_write.return_value = Path("/mock/prompt.md")
                mock_build.return_value = "research prompt"
                updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify research task was dispatched
            self.assertIn("research_tasks", updates)
            self.assertEqual("dispatched", updates["research_tasks"].get("auth"))

            # Simulate research completion
            state = load_state(state_path)
            state["research_tasks"] = {"auth": "dispatched"}
            write_state(state_path, state)
            (research_dir / "done").touch()

            event = WorkflowEvent(
                kind="file.created", path="03_research/code-auth/done"
            )
            updates, next_phase = router.handle(event, load_state(state_path), ctx)

            # Verify research task was marked done
            self.assertIn("research_tasks", updates)
            self.assertEqual("done", updates["research_tasks"].get("auth"))

            # Verify planner was notified
            self.assertTrue(
                any("planner" in role for role, _ in ctx.runtime.notifications)
            )


if __name__ == "__main__":
    unittest.main()
