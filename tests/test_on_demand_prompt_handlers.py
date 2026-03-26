from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.shared.models import AgentConfig
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.workflow.phases import get_phase, run_phase_cycle
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


def _make_ctx(feature_dir: Path, with_docs: bool = True) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "on demand prompt generation", "session-x")
    architect_prompt = feature_dir / "02_planning" / "architect_prompt.md"
    architect_prompt.parent.mkdir(parents=True, exist_ok=True)
    architect_prompt.write_text("architect prompt", encoding="utf-8")
    agents = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "reviewer": AgentConfig(role="reviewer", cli="claude", model="sonnet", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    if with_docs:
        agents["docs"] = AgentConfig(role="docs", cli="codex", model="gpt-5.3-codex", args=[])
    ctx = PipelineContext(
        files=files,
        runtime=FakeRuntime(),
        agents=agents,
        max_review_iterations=3,
        prompts={"architect": architect_prompt},
    )
    return ctx, files.state


class OnDemandPromptHandlerTests(unittest.TestCase):
    def test_enter_implementing_builds_coder_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            ctx.files.plan.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.plan.write_text("# Plan\n\n1. Implement\n", encoding="utf-8")
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)
            updated = load_state(state_path)

            self.assertTrue((ctx.files.implementation_dir / "coder_prompt.md").exists())
            self.assertEqual(
                [("kill_primary", "coder"), ("send", "coder", "coder_prompt.md", "[coder] implementation")],
                ctx.runtime.calls,
            )
            self.assertEqual(1, updated["implementation_group_total"])
            self.assertEqual(1, updated["implementation_group_index"])
            self.assertEqual("serial", updated["implementation_group_mode"])
            self.assertEqual(["plan_1"], updated["implementation_active_plan_ids"])
            self.assertEqual([], updated["implementation_completed_group_ids"])

    def test_enter_implementing_with_subplans_records_parallel_group_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            ctx.files.plan.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.plan.write_text(
                "# Plan\n\n## Sub-plan 1: A\n\nDo A\n\n## Sub-plan 2: B\n\nDo B\n",
                encoding="utf-8",
            )
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)
            updated = load_state(state_path)

            self.assertEqual(
                [("kill_primary", "coder"), ("send_many", "coder", ["coder_prompt_1.txt", "coder_prompt_2.txt"])],
                ctx.runtime.calls,
            )
            self.assertEqual(
                [[(1, "coder_prompt_1.txt", "[coder] A"), (2, "coder_prompt_2.txt", "[coder] B")]],
                ctx.runtime.parallel_specs,
            )
            self.assertEqual(1, updated["implementation_group_total"])
            self.assertEqual(1, updated["implementation_group_index"])
            self.assertEqual("parallel", updated["implementation_group_mode"])
            self.assertEqual(["plan_1", "plan_2"], updated["implementation_active_plan_ids"])
            self.assertEqual([], updated["implementation_completed_group_ids"])

    def test_implementing_hides_completed_subplan_when_other_coders_remain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            ctx.files.plan.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.plan.write_text(
                "# Plan\n\n## Sub-plan 1: A\n\nDo A\n\n## Sub-plan 2: B\n\nDo B\n",
                encoding="utf-8",
            )
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)
            phase = get_phase(load_state(state_path))
            self.assertEqual("parallel", load_state(state_path)["implementation_group_mode"])

            ctx.files.implementation_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.implementation_dir / "done_1").write_text("", encoding="utf-8")
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("subplan_completed:1", event)

            result = phase.handle_event(load_state(state_path), event, ctx)

            self.assertIsNone(result)
            self.assertEqual(
                [
                    ("kill_primary", "coder"),
                    ("send_many", "coder", ["coder_prompt_1.txt", "coder_prompt_2.txt"]),
                    ("hide_task", "coder", 1),
                ],
                ctx.runtime.calls,
            )
            updated = load_state(state_path)
            self.assertEqual([1], updated["completed_subplans"])
            self.assertIsNone(phase.detect_event(updated, ctx))

    def test_enter_reviewing_builds_review_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertTrue((ctx.files.review_dir / "review_prompt.md").exists())
            self.assertEqual([("send", "reviewer", "review_prompt.md", "[reviewer] iteration 1")], ctx.runtime.calls)

    def test_enter_fixing_kills_stale_coder_and_builds_fix_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["phase"] = "fixing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertTrue((ctx.files.review_dir / "fix_prompt.txt").exists())
            self.assertEqual(
                [("kill_primary", "coder"), ("send", "coder", "fix_prompt.txt", "[coder] fix 1")],
                ctx.runtime.calls,
            )

    def test_enter_completing_builds_confirmation_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature", with_docs=True)
            state = load_state(state_path)
            state["phase"] = "completing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertTrue((ctx.files.completion_dir / "confirmation_prompt.md").exists())
            self.assertEqual([("send", "reviewer", "confirmation_prompt.md", "[reviewer] iteration 1")], ctx.runtime.calls)


if __name__ == "__main__":
    unittest.main()
