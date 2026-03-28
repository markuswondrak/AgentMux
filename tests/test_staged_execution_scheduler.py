from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files, infer_resume_phase, load_state, write_state
from agentmux.shared.models import AgentConfig
from agentmux.workflow.phases import run_phase_cycle
from agentmux.workflow.transitions import PipelineContext


def _prompt_names(prompt_specs: list[object]) -> list[str]:
    names: list[str] = []
    for item in prompt_specs:
        prompt_file = getattr(item, "prompt_file", item)
        names.append(Path(prompt_file).name)
    return names


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.parallel_specs: list[list[tuple[int | str, str, str | None]]] = []

    def send(self, role: str, prompt_file: Path, display_label: str | None = None) -> None:
        self.calls.append(("send", role, prompt_file.name, display_label))

    def send_many(self, role: str, prompt_specs: list[object]) -> None:
        self.calls.append(("send_many", role, _prompt_names(prompt_specs)))
        self.parallel_specs.append(
            [
                (
                    getattr(item, "task_id"),
                    Path(getattr(item, "prompt_file")).name,
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

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


def _make_ctx(feature_dir: Path) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "staged execution", "session-x")
    ctx = PipelineContext(
        files=files,
        runtime=_FakeRuntime(),
        agents={
            "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
            "reviewer": AgentConfig(role="reviewer", cli="claude", model="sonnet", args=[]),
        },
        max_review_iterations=3,
        prompts={},
    )
    return ctx, files.state


def _set_phase(state_path: Path, phase: str) -> None:
    state = load_state(state_path)
    state["phase"] = phase
    write_state(state_path, state)


def _cycle(ctx: PipelineContext, state_path: Path) -> dict:
    state = load_state(state_path)
    run_phase_cycle(state, ctx)
    return load_state(state_path)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _write_execution_plan(ctx: PipelineContext, groups: list[dict]) -> None:
    planning_dir = ctx.files.planning_dir
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    payload = {"version": 1, "groups": groups}
    (planning_dir / "execution_plan.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for group in groups:
        for plan_file in group["plans"]:
            plan_ref = plan_file["file"] if isinstance(plan_file, dict) else plan_file
            (planning_dir / plan_ref).write_text(f"# {plan_ref}\n", encoding="utf-8")


class StagedExecutionSchedulerTests(unittest.TestCase):
    def test_serial_schedule_runs_single_group_then_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            _set_phase(state_path, "implementing")
            _write_execution_plan(
                ctx,
                [{"group_id": "g1", "mode": "serial", "plans": [{"file": "plan_1.md", "name": "Foundation"}]}],
            )

            _cycle(ctx, state_path)
            self.assertIn(("send", "coder", "coder_prompt_1.txt", "[coder] Foundation"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("reviewing", state["phase"])

    def test_parallel_schedule_waits_for_all_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            _set_phase(state_path, "implementing")
            _write_execution_plan(
                ctx,
                [
                    {
                        "group_id": "g1",
                        "mode": "parallel",
                        "plans": [
                            {"file": "plan_1.md", "name": "Foundation"},
                            {"file": "plan_2.md", "name": "API wiring"},
                        ],
                    }
                ],
            )

            _cycle(ctx, state_path)
            self.assertIn(("send_many", "coder", ["coder_prompt_1.txt", "coder_prompt_2.txt"]), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])

            _touch(ctx.files.implementation_dir / "done_2")
            state = _cycle(ctx, state_path)
            self.assertEqual("reviewing", state["phase"])

    def test_mixed_schedule_dispatches_waves_and_only_finishes_after_last_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            _set_phase(state_path, "implementing")
            _write_execution_plan(
                ctx,
                [
                    {"group_id": "g1", "mode": "serial", "plans": [{"file": "plan_1.md", "name": "Foundation"}]},
                    {
                        "group_id": "g2",
                        "mode": "parallel",
                        "plans": [
                            {"file": "plan_2.md", "name": "API wiring"},
                            {"file": "plan_3.md", "name": "UI polish"},
                        ],
                    },
                    {"group_id": "g3", "mode": "serial", "plans": [{"file": "plan_4.md", "name": "Integration"}]},
                ],
            )

            _cycle(ctx, state_path)
            self.assertIn(("send", "coder", "coder_prompt_1.txt", "[coder] Foundation"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertIn(("send_many", "coder", ["coder_prompt_2.txt", "coder_prompt_3.txt"]), ctx.runtime.calls)
            self.assertIn(
                [(2, "coder_prompt_2.txt", "[coder] API wiring"), (3, "coder_prompt_3.txt", "[coder] UI polish")],
                ctx.runtime.parallel_specs,
            )

            _touch(ctx.files.implementation_dir / "done_2")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])

            _touch(ctx.files.implementation_dir / "done_3")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertIn(("send", "coder", "coder_prompt_4.txt", "[coder] Integration"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_4")
            state = _cycle(ctx, state_path)
            self.assertEqual("reviewing", state["phase"])

    def test_resume_during_parallel_group_only_redispatches_pending_work(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = _make_ctx(feature_dir)
            _set_phase(state_path, "implementing")
            _write_execution_plan(
                ctx,
                [
                    {"group_id": "g1", "mode": "serial", "plans": [{"file": "plan_1.md", "name": "Foundation"}]},
                    {
                        "group_id": "g2",
                        "mode": "parallel",
                        "plans": [
                            {"file": "plan_2.md", "name": "API wiring"},
                            {"file": "plan_3.md", "name": "UI polish"},
                        ],
                    },
                    {"group_id": "g3", "mode": "serial", "plans": [{"file": "plan_4.md", "name": "Integration"}]},
                ],
            )

            _cycle(ctx, state_path)
            _touch(ctx.files.implementation_dir / "done_1")
            _cycle(ctx, state_path)
            _touch(ctx.files.implementation_dir / "done_2")

            state = load_state(state_path)
            state["phase"] = "failed"
            state["last_event"] = "run_failed"
            write_state(state_path, state)

            resumed_state = load_state(state_path)
            resumed_phase = infer_resume_phase(feature_dir, resumed_state)
            self.assertEqual("implementing", resumed_phase)
            resumed_state["phase"] = resumed_phase
            resumed_state["last_event"] = "resumed"
            write_state(state_path, resumed_state)

            resumed_ctx = PipelineContext(
                files=ctx.files,
                runtime=_FakeRuntime(),
                agents=ctx.agents,
                max_review_iterations=ctx.max_review_iterations,
                prompts=ctx.prompts,
            )
            _cycle(resumed_ctx, state_path)
            self.assertIn(("send", "coder", "coder_prompt_3.txt", "[coder] UI polish"), resumed_ctx.runtime.calls)
            self.assertNotIn(("send", "coder", "coder_prompt_2.txt", "[coder] API wiring"), resumed_ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_3")
            state = _cycle(resumed_ctx, state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertIn(("send", "coder", "coder_prompt_4.txt", "[coder] Integration"), resumed_ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_4")
            state = _cycle(resumed_ctx, state_path)
            self.assertEqual("reviewing", state["phase"])

    def test_fixing_phase_completes_on_done_1_even_with_multiple_subplans(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            state = load_state(state_path)
            state["phase"] = "fixing"
            state["subplan_count"] = 4
            write_state(state_path, state)

            _cycle(ctx, state_path)
            self.assertIn(("send", "coder", "fix_prompt.txt", "[coder] fix 1"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("reviewing", state["phase"])


if __name__ == "__main__":
    unittest.main()
