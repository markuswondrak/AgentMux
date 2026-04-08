from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.completion import CompletionResult
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import AgentConfig, GitHubConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import (
    PHASE_HANDLERS,
    PlanningHandler,
    ProductManagementHandler,
)
from agentmux.workflow.prompts import build_architect_prompt
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
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(payload, default_flow_style=False), encoding="utf-8")


def _write_execution_plan(
    files, *, name: str = "implementation", **meta: object
) -> None:
    files.planning_dir.mkdir(parents=True, exist_ok=True)
    (files.planning_dir / "plan_1.md").write_text(
        f"## Sub-plan 1: {name}\n", encoding="utf-8"
    )
    data: dict[str, object] = {
        "groups": [
            {
                "group_id": "g1",
                "mode": "serial",
                "plans": [{"file": "plan_1.md", "name": name}],
            }
        ],
    }
    data.update(meta)
    _write_yaml(files.execution_plan, data)


def _proposal_payload(
    source_role: str, bullet: str, target_role: str = "coder"
) -> dict[str, object]:
    return {
        "source_role": source_role,
        "approved": [{"target_role": target_role, "bullet": bullet}],
    }


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
    def test_architecture_submission_materializes_tool_payload_preferences(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "architecting"
            write_state(state_path, state)

            # Architect writes architecture.md and approved_preferences.json directly.
            ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.planning_dir / "architecture.md").write_text(
                "# Architecture\n\nSimple layered architecture.\n", encoding="utf-8"
            )
            _write_json(
                ctx.files.architect_preference_proposal,
                _proposal_payload("architect", "Keep coder changes narrowly scoped"),
            )

            handler = PHASE_HANDLERS.get("architecting")
            assert handler is not None
            event = WorkflowEvent(kind="architecture", payload={"payload": {}})

            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("architecting", state["phase"])
            self.assertEqual("planning", next_phase)
            self.assertEqual("architecture_written", updates.get("last_event"))
            self.assertTrue(ctx.files.architect_preference_proposal.is_file())
            self.assertIn(
                '"source_role": "architect"',
                ctx.files.architect_preference_proposal.read_text(encoding="utf-8"),
            )
            target = (
                ctx.files.project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            )
            self.assertTrue(target.is_file())
            self.assertIn(
                "- Keep coder changes narrowly scoped",
                target.read_text(encoding="utf-8"),
            )

    def test_pm_completed_applies_approved_preferences_before_planning_transition(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)
            _write_json(
                ctx.files.pm_preference_proposal,
                {
                    "source_role": "product-manager",
                    "approved": [
                        {"target_role": "architect", "bullet": "Keep plans executable"}
                    ],
                },
            )

            handler = ProductManagementHandler()
            event = WorkflowEvent(
                kind="pm_done",
                payload={"payload": {}},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            target = (
                ctx.files.project_dir
                / ".agentmux"
                / "prompts"
                / "agents"
                / "architect.md"
            )
            self.assertTrue(target.is_file())
            self.assertIn("- Keep plans executable", target.read_text(encoding="utf-8"))
            self.assertEqual("architecting", next_phase)
            self.assertEqual("pm_completed", updates.get("last_event"))

    def test_pm_completed_without_proposal_file_is_prompt_extension_noop(self) -> None:
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
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            prompts_dir = ctx.files.project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())

    def test_plan_written_applies_architect_preferences_before_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=False)

            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)
            _write_plan_yaml(ctx.files, needs_design=False)
            _write_json(
                ctx.files.architect_preference_proposal,
                {
                    "source_role": "architect",
                    "approved": [
                        {
                            "target_role": "reviewer",
                            "bullet": "Call out regressions first",
                        }
                    ],
                },
            )

            handler = PlanningHandler()
            event = WorkflowEvent(kind="plan", payload={"payload": {}})
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            target = (
                ctx.files.project_dir
                / ".agentmux"
                / "prompts"
                / "agents"
                / "reviewer.md"
            )
            self.assertTrue(target.is_file())
            self.assertIn(
                "- Call out regressions first", target.read_text(encoding="utf-8")
            )
            self.assertEqual("implementing", next_phase)
            self.assertEqual("plan_written", updates.get("last_event"))

    def test_plan_written_without_proposal_file_is_prompt_extension_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=False)

            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)
            _write_plan_yaml(ctx.files, needs_design=False)

            handler = PlanningHandler()
            event = WorkflowEvent(kind="plan", payload={"payload": {}})
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            prompts_dir = ctx.files.project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())

    def test_plan_written_materializes_tool_payload_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=False)

            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)

            plan_data: dict = {
                "version": 2,
                "plan_overview": "# Plan\n\nImplementation plan.",
                "groups": [
                    {
                        "group_id": "g1",
                        "mode": "serial",
                        "plans": [{"index": 1, "name": "implementation"}],
                    }
                ],
                "subplans": [
                    {
                        "index": 1,
                        "title": "implementation",
                        "scope": "Core implementation",
                        "owned_files": ["src/feature.py"],
                        "dependencies": "None",
                        "implementation_approach": "Implement feature",
                        "acceptance_criteria": "Tests pass",
                        "tasks": ["Implement feature"],
                    }
                ],
                "review_strategy": {"severity": "medium", "focus": []},
                "needs_design": False,
                "needs_docs": False,
                "doc_files": [],
                "approved_preferences": _proposal_payload(
                    "planner", "Validate each task before marking done"
                ),
            }
            _write_yaml(ctx.files.planning_dir / "plan.yaml", plan_data)

            handler = PlanningHandler()
            event = WorkflowEvent(kind="plan", payload={"payload": {}})

            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("implementing", next_phase)
            self.assertEqual("plan_written", updates.get("last_event"))
            target = (
                ctx.files.project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            )
            self.assertTrue(target.is_file())
            self.assertIn(
                "- Validate each task before marking done",
                target.read_text(encoding="utf-8"),
            )
            # No intermediate JSON file is written for planner preferences.
            self.assertFalse(ctx.files.architect_preference_proposal.is_file())

    def test_approval_received_applies_reviewer_preferences_before_changed_file_scan(
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
                    "commit_message": "complete",
                    "exclude_files": [],
                },
            )
            _write_json(
                ctx.files.reviewer_preference_proposal,
                {
                    "source_role": "reviewer",
                    "approved": [
                        {"target_role": "coder", "bullet": "Prefer tight unit tests"}
                    ],
                },
            )

            target = (
                ctx.files.project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            )

            def _status_with_assertions(project_dir: Path) -> str:
                _ = project_dir
                self.assertTrue(target.is_file())
                self.assertIn(
                    "- Prefer tight unit tests", target.read_text(encoding="utf-8")
                )
                return " M .agentmux/prompts/agents/coder.md\n"

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    side_effect=_status_with_assertions,
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
            self.assertIn(
                ".agentmux/prompts/agents/coder.md",
                finalize_mock.call_args.kwargs["changed_paths"],
            )

    def test_review_submission_does_not_materialize_reviewer_preferences(
        self,
    ) -> None:
        """Reviewer preferences in review.yaml are applied only by the reviewer agent
        during the summary step — the reviewing handler no longer materializes them."""
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            review_data = {
                "verdict": "fail",
                "summary": "Issues found",
                "findings": [
                    {
                        "location": "src/x.py:10",
                        "issue": "Missing validation",
                        "severity": "high",
                        "recommendation": "Add check",
                    }
                ],
                "approved_preferences": _proposal_payload(
                    "reviewer", "Prefer focused regression coverage"
                ),
            }
            _write_yaml(ctx.files.review_dir / "review.yaml", review_data)

            handler = PHASE_HANDLERS.get("reviewing")
            assert handler is not None
            event = WorkflowEvent(kind="review", payload={"payload": {}})

            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("fixing", next_phase)
            self.assertEqual("review_failed", updates.get("last_event"))
            # No intermediate JSON file is materialized — the reviewer agent writes it
            # directly during the summary step.
            self.assertFalse(ctx.files.reviewer_preference_proposal.is_file())

    def test_approval_received_without_proposal_file_is_prompt_extension_noop(
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

    def test_changes_requested_does_not_apply_reviewer_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "completing"
            write_state(state_path, state)
            _write_json(
                ctx.files.reviewer_preference_proposal,
                {
                    "source_role": "reviewer",
                    "approved": [
                        {"target_role": "coder", "bullet": "Prefer narrow diffs"}
                    ],
                },
            )

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            event = WorkflowEvent(
                kind="changes_requested",
                path="08_completion/changes.md",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("planning", next_phase)
            self.assertEqual("changes_requested", updates.get("last_event"))
            target = (
                ctx.files.project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            )
            self.assertFalse(target.exists())

    def test_persisted_pm_preference_is_visible_in_later_architect_prompt_build(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)
            _write_json(
                ctx.files.pm_preference_proposal,
                {
                    "source_role": "product-manager",
                    "approved": [
                        {
                            "target_role": "architect",
                            "bullet": "Keep plans customer-centric",
                        }
                    ],
                },
            )

            handler = ProductManagementHandler()
            event = WorkflowEvent(
                kind="pm_done",
                payload={"payload": {}},
            )
            handler.handle_event(event, load_state(state_path), ctx)
            prompt = build_architect_prompt(ctx.files)

            self.assertIn("Keep plans customer-centric", prompt)

    def test_dismissed_candidates_payload_does_not_modify_prompt_extensions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)
            _write_json(
                ctx.files.pm_preference_proposal,
                {
                    "source_role": "product-manager",
                    "approved": [],
                },
            )

            handler = ProductManagementHandler()
            event = WorkflowEvent(
                kind="pm_done",
                payload={"payload": {}},
            )
            handler.handle_event(event, load_state(state_path), ctx)

            prompts_dir = ctx.files.project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())

    def test_approval_received_appends_reviewer_preference_once(self) -> None:
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
                    "commit_message": "complete",
                    "exclude_files": [],
                },
            )
            _write_json(
                ctx.files.reviewer_preference_proposal,
                {
                    "source_role": "reviewer",
                    "approved": [
                        {"target_role": "coder", "bullet": "Prefer narrow changesets"},
                        {
                            "target_role": "coder",
                            "bullet": "* prefer narrow changesets",
                        },
                    ],
                },
            )

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    return_value=" M .agentmux/prompts/agents/coder.md\n",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
                    return_value=CompletionResult(
                        commit_hash=None,
                        pr_url=None,
                        cleaned_up=False,
                        should_cleanup=False,
                    ),
                ),
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
            target = (
                ctx.files.project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            )
            self.assertTrue(target.is_file())
            self.assertEqual(
                1,
                target.read_text(encoding="utf-8").count("- Prefer narrow changesets"),
            )


if __name__ == "__main__":
    unittest.main()
