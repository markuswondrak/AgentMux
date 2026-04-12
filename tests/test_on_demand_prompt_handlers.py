from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import AgentConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import (
    CompletingHandler,
    FixingHandler,
    ImplementingHandler,
    ReviewingHandler,
)
from agentmux.workflow.transitions import PipelineContext


def _prompt_names(prompt_specs: list[object]) -> list[str]:
    names: list[str] = []
    for item in prompt_specs:
        prompt_file = getattr(item, "prompt_file", item)
        names.append(Path(prompt_file).name)
    return names


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.parallel_specs: list[list[tuple[int | str, str, str | None]]] = []

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
        self.calls.append(("send_many", role, _prompt_names(prompt_specs)))
        self.parallel_specs.append(
            [
                (
                    item.task_id,
                    Path(item.prompt_file).name,
                    getattr(item, "display_label", None),
                )
                for item in prompt_specs
            ]
        )

    def deactivate(self, role: str) -> None:
        self.calls.append(("deactivate", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))

    def hide_task(self, role: str, task_id: int | str) -> None:
        self.calls.append(("hide_task", role, task_id))

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def show_completion_ui(self, feature_dir: Path) -> None:
        self.calls.append(("show_completion_ui", str(feature_dir)))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


def _make_ctx(feature_dir: Path) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(
        project_dir, feature_dir, "on demand prompt generation", "session-x"
    )
    files.plan.parent.mkdir(parents=True, exist_ok=True)
    files.plan.write_text("# Plan\n", encoding="utf-8")
    files.tasks.parent.mkdir(parents=True, exist_ok=True)
    files.tasks.write_text("# Tasks\n\n- [ ] one task\n", encoding="utf-8")
    files.fix_request.parent.mkdir(parents=True, exist_ok=True)
    files.fix_request.write_text("# Fix request\n", encoding="utf-8")
    files.review.parent.mkdir(parents=True, exist_ok=True)
    files.review.write_text("verdict: pass\n", encoding="utf-8")

    # Create required files for reviewer prompts
    files.context.write_text("# Context", encoding="utf-8")
    files.architecture.parent.mkdir(parents=True, exist_ok=True)
    files.architecture.write_text("# Architecture", encoding="utf-8")

    architect_prompt = feature_dir / "02_architecting" / "architect_prompt.md"
    architect_prompt.parent.mkdir(parents=True, exist_ok=True)
    architect_prompt.write_text("architect prompt", encoding="utf-8")
    agents = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "reviewer": AgentConfig(role="reviewer", cli="claude", model="sonnet", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    ctx = PipelineContext(
        files=files,
        runtime=FakeRuntime(),
        agents=agents,
        max_review_iterations=3,
        prompts={"architect": architect_prompt},
    )
    return ctx, files.state


def _write_execution_plan(
    feature_dir: Path, plans: list[tuple[int, str]], *, mode: str
) -> None:
    planning_dir = feature_dir / "04_planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    for index, name in plans:
        (planning_dir / f"plan_{index}.md").write_text(
            f"## Sub-plan {index}: {name}\n", encoding="utf-8"
        )
        # Create per-plan tasks file for each plan
        (planning_dir / f"tasks_{index}.md").write_text(
            f"# Tasks for plan {index}\n\n- [ ] execute sub-plan {index}\n",
            encoding="utf-8",
        )
    import yaml

    (planning_dir / "execution_plan.yaml").write_text(
        yaml.dump(
            {
                "groups": [
                    {
                        "group_id": "g1",
                        "mode": mode,
                        "plans": [
                            {"file": f"plan_{index}.md", "name": name}
                            for index, name in plans
                        ],
                    }
                ],
            },
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


class OnDemandPromptHandlerTests(unittest.TestCase):
    def test_enter_implementing_builds_numbered_coder_prompt_for_single_plan_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            _write_execution_plan(
                ctx.files.feature_dir, [(1, "implementation")], mode="serial"
            )
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            handler = ImplementingHandler()
            updates = handler.enter(load_state(state_path), ctx)
            updated = load_state(state_path)
            updated.update(updates)

            self.assertTrue(
                (ctx.files.implementation_dir / "coder_prompt_1.md").exists()
            )
            self.assertEqual(
                [
                    ("kill_primary", "coder"),
                    (
                        "send",
                        "coder",
                        "coder_prompt_1.md",
                        "[coder] implementation",
                        None,
                    ),
                ],
                ctx.runtime.calls,
            )
            self.assertEqual(1, updated.get("implementation_group_total"))
            self.assertEqual(1, updated.get("implementation_group_index"))
            self.assertEqual("serial", updated.get("implementation_group_mode"))
            self.assertEqual(["plan_1"], updated.get("implementation_active_plan_ids"))
            self.assertEqual([], updated.get("implementation_completed_group_ids"))

    def test_enter_implementing_with_subplans_records_parallel_group_progress(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            _write_execution_plan(
                ctx.files.feature_dir, [(1, "A"), (2, "B")], mode="parallel"
            )
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            handler = ImplementingHandler()
            updates = handler.enter(load_state(state_path), ctx)
            updated = load_state(state_path)
            updated.update(updates)

            self.assertEqual(
                [
                    ("kill_primary", "coder"),
                    (
                        "send_many",
                        "coder",
                        ["coder_prompt_1.md", "coder_prompt_2.md"],
                    ),
                ],
                ctx.runtime.calls,
            )
            self.assertEqual(
                [
                    [
                        (1, "coder_prompt_1.md", "[coder] A"),
                        (2, "coder_prompt_2.md", "[coder] B"),
                    ]
                ],
                ctx.runtime.parallel_specs,
            )
            self.assertEqual(1, updated.get("implementation_group_total"))
            self.assertEqual(1, updated.get("implementation_group_index"))
            self.assertEqual("parallel", updated.get("implementation_group_mode"))
            self.assertEqual(
                ["plan_1", "plan_2"], updated.get("implementation_active_plan_ids")
            )
            self.assertEqual([], updated.get("implementation_completed_group_ids"))

    def test_implementing_hides_completed_subplan_when_other_coders_remain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            _write_execution_plan(
                ctx.files.feature_dir, [(1, "A"), (2, "B")], mode="parallel"
            )
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            handler = ImplementingHandler()
            updates = handler.enter(load_state(state_path), ctx)
            state = load_state(state_path)
            state.update(updates)
            write_state(state_path, state)

            self.assertEqual("parallel", state.get("implementation_group_mode"))

            ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
            event = WorkflowEvent(
                kind="done",
                payload={"payload": {"subplan_index": 1}},
            )
            updates, next_phase = handler.handle_event(event, state, ctx)
            state.update(updates)
            write_state(state_path, state)

            self.assertIsNone(next_phase)
            self.assertEqual(
                [
                    ("kill_primary", "coder"),
                    (
                        "send_many",
                        "coder",
                        ["coder_prompt_1.md", "coder_prompt_2.md"],
                    ),
                    ("hide_task", "coder", 1),
                ],
                ctx.runtime.calls,
            )
            self.assertEqual([1], state.get("completed_subplans"))

    def test_enter_reviewing_builds_review_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertTrue((ctx.files.review_dir / "review_logic_prompt.md").exists())
            self.assertEqual(
                [
                    (
                        "send",
                        "reviewer_logic",
                        "review_logic_prompt.md",
                        "[reviewer_logic] logic",
                        None,
                    )
                ],
                ctx.runtime.calls,
            )

    def test_enter_fixing_kills_stale_coder_and_builds_fix_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["phase"] = "fixing"
            write_state(state_path, state)

            handler = FixingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertTrue((ctx.files.review_dir / "fix_prompt.md").exists())
            self.assertEqual(
                [
                    ("kill_primary", "coder"),
                    ("send", "coder", "fix_prompt.md", "[coder] fix 1", None),
                ],
                ctx.runtime.calls,
            )

    def test_enter_completing_launches_completion_ui(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["phase"] = "completing"
            write_state(state_path, state)

            handler = CompletingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertTrue(
                any(c[0] == "show_completion_ui" for c in ctx.runtime.calls),
                f"Expected show_completion_ui call, got: {ctx.runtime.calls}",
            )
            self.assertFalse(
                any(c[0] == "send" for c in ctx.runtime.calls),
                f"Expected no send calls, got: {ctx.runtime.calls}",
            )


if __name__ == "__main__":
    unittest.main()
