from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files, infer_resume_phase, load_state, write_state
from agentmux.shared.models import AgentConfig
from agentmux.workflow.phases import run_phase_cycle
from agentmux.workflow.transitions import PipelineContext


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def send(self, role: str, prompt_file: Path) -> None:
        self.calls.append(("send", role, prompt_file.name))

    def send_many(self, role: str, prompt_files: list[Path]) -> None:
        self.calls.append(("send_many", role, [path.name for path in prompt_files]))

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
            (planning_dir / plan_file).write_text(f"# {plan_file}\n", encoding="utf-8")


class StagedExecutionSchedulerTests(unittest.TestCase):
    def test_serial_schedule_runs_single_group_then_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            _set_phase(state_path, "implementing")
            _write_execution_plan(
                ctx,
                [{"group_id": "g1", "mode": "serial", "plans": ["plan_1.md"]}],
            )

            _cycle(ctx, state_path)
            self.assertIn(("send", "coder", "coder_prompt_1.txt"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("reviewing", state["phase"])

    def test_parallel_schedule_waits_for_all_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            _set_phase(state_path, "implementing")
            _write_execution_plan(
                ctx,
                [{"group_id": "g1", "mode": "parallel", "plans": ["plan_1.md", "plan_2.md"]}],
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
                    {"group_id": "g1", "mode": "serial", "plans": ["plan_1.md"]},
                    {"group_id": "g2", "mode": "parallel", "plans": ["plan_2.md", "plan_3.md"]},
                    {"group_id": "g3", "mode": "serial", "plans": ["plan_4.md"]},
                ],
            )

            _cycle(ctx, state_path)
            self.assertIn(("send", "coder", "coder_prompt_1.txt"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertIn(("send_many", "coder", ["coder_prompt_2.txt", "coder_prompt_3.txt"]), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_2")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])

            _touch(ctx.files.implementation_dir / "done_3")
            state = _cycle(ctx, state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertIn(("send", "coder", "coder_prompt_4.txt"), ctx.runtime.calls)

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
                    {"group_id": "g1", "mode": "serial", "plans": ["plan_1.md"]},
                    {"group_id": "g2", "mode": "parallel", "plans": ["plan_2.md", "plan_3.md"]},
                    {"group_id": "g3", "mode": "serial", "plans": ["plan_4.md"]},
                ],
            )

            _cycle(ctx, state_path)
            _touch(ctx.files.implementation_dir / "done_1")
            _cycle(ctx, state_path)
            _touch(ctx.files.implementation_dir / "done_2")

            state = load_state(state_path)
            state["phase"] = "failed"
            state["last_event"] = "pipeline_exception"
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
            self.assertIn(("send", "coder", "coder_prompt_3.txt"), resumed_ctx.runtime.calls)
            self.assertNotIn(("send", "coder", "coder_prompt_2.txt"), resumed_ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_3")
            state = _cycle(resumed_ctx, state_path)
            self.assertEqual("implementing", state["phase"])
            self.assertIn(("send", "coder", "coder_prompt_4.txt"), resumed_ctx.runtime.calls)

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
            self.assertIn(("send", "coder", "fix_prompt.txt"), ctx.runtime.calls)

            _touch(ctx.files.implementation_dir / "done_1")
            state = _cycle(ctx, state_path)
            self.assertEqual("reviewing", state["phase"])


if __name__ == "__main__":
    unittest.main()
