from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agentmux.integrations.completion import CompletionResult
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import AgentConfig, GitHubConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import (
    PHASE_HANDLERS,
    PlanningHandler,
    ProductManagementHandler,
)
from agentmux.workflow.transitions import PipelineContext


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

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

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def deactivate(self, role: str) -> None:
        self.calls.append(("deactivate", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))


def _make_ctx(
    feature_dir: Path, *, with_designer: bool = False
) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(
        project_dir, feature_dir, "preference workflow", "session-x"
    )
    agents = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
        "reviewer": AgentConfig(role="reviewer", cli="claude", model="sonnet", args=[]),
    }
    if with_designer:
        agents["designer"] = AgentConfig(
            role="designer", cli="claude", model="sonnet", args=[]
        )
    ctx = PipelineContext(
        files=files,
        runtime=_FakeRuntime(),
        agents=agents,
        max_review_iterations=3,
        prompts={},
        github_config=GitHubConfig(),
    )
    return ctx, files.state


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(payload, default_flow_style=False), encoding="utf-8")


def _write_plan_yaml(files, *, name: str = "implementation", **meta: object) -> None:
    """Write plan.yaml (version 2) to disk for testing PlanningHandler."""
    files.planning_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {
        "version": 2,
        "plan_overview": f"# Plan\n\n{name} plan.",
        "groups": [
            {"group_id": "g1", "mode": "serial", "plans": [{"index": 1, "name": name}]}
        ],
        "subplans": [
            {
                "index": 1,
                "title": name,
                "scope": "Core implementation",
                "owned_files": ["src/feature.py"],
                "dependencies": "None",
                "implementation_approach": "Implement the feature",
                "acceptance_criteria": "Tests pass",
                "tasks": ["Implement feature"],
            }
        ],
        "review_strategy": {"severity": "medium", "focus": []},
        "needs_design": False,
        "needs_docs": False,
        "doc_files": [],
    }
    data.update(meta)
    _write_yaml(files.planning_dir / "plan.yaml", data)


class PreferenceMemoryWorkflowRequirementsTests(unittest.TestCase):
    def test_pm_completed_without_preferences_leaves_prompts_dir_untouched(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)

            handler = ProductManagementHandler()
            event = WorkflowEvent(
                kind="pm_done",
                payload={"payload": {}},
            )
            handler.handle_event(event, load_state(state_path), ctx)

            prompts_dir = ctx.files.project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())

    def test_plan_written_without_preferences_leaves_prompts_dir_untouched(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=False)

            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)
            _write_plan_yaml(ctx.files, needs_design=False)

            handler = PlanningHandler()
            event = WorkflowEvent(kind="plan", payload={"payload": {}})
            handler.handle_event(event, load_state(state_path), ctx)

            prompts_dir = ctx.files.project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())

    def test_approval_received_without_preferences_leaves_prompts_dir_untouched(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            _write_json(
                ctx.files.completion_dir / "approval.json",
                {
                    "action": "approve",
                    "commit_message": "complete",
                    "exclude_files": [],
                },
            )

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    return_value=" M agentmux/workflow/handlers/completing.py\n",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
                    return_value=CompletionResult(
                        commit_hash=None,
                        pr_url=None,
                        cleaned_up=False,
                        should_cleanup=False,
                    ),
                ) as finalize_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = handler.handle_event(
                    event, load_state(state_path), ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": False}, updates)
            self.assertIsNone(next_phase)
            self.assertEqual(
                "complete", finalize_mock.call_args.kwargs["commit_message"]
            )
            prompts_dir = ctx.files.project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())

    def test_approval_received_without_commit_message_uses_drafted_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "completing"
            write_state(state_path, state)
            _write_json(
                ctx.files.completion_dir / "approval.json",
                {
                    "action": "approve",
                    "exclude_files": [],
                },
            )

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    return_value=" M agentmux/workflow/handlers/completing.py\n",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.draft_commit_message",
                    return_value="feat: drafted fallback",
                ) as draft_mock,
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
                    return_value=CompletionResult(
                        commit_hash=None,
                        pr_url=None,
                        cleaned_up=False,
                        should_cleanup=False,
                    ),
                ) as finalize_mock,
            ):
                event = WorkflowEvent(
                    kind="approval_received",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = handler.handle_event(
                    event, load_state(state_path), ctx
                )

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": False}, updates)
            self.assertIsNone(next_phase)
            draft_mock.assert_called_once_with(
                files=ctx.files,
                issue_number=None,
            )
            self.assertEqual(
                "feat: drafted fallback",
                finalize_mock.call_args.kwargs["commit_message"],
            )


if __name__ == "__main__":
    unittest.main()
