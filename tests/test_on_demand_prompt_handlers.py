from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.models import AgentConfig
from agentmux.phases import run_phase_cycle
from agentmux.state import create_feature_files, load_state, write_state
from agentmux.transitions import PipelineContext


class FakeRuntime:
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

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


def _make_ctx(feature_dir: Path, with_docs: bool = True) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "on demand prompt generation", "session-x")
    architect_prompt = feature_dir / "planning" / "architect_prompt.md"
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
            ctx.files.plan.write_text("# Plan\n\n1. Implement\n", encoding="utf-8")
            state = load_state(state_path)
            state["phase"] = "implementing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertTrue((ctx.files.implementation_dir / "coder_prompt.md").exists())
            self.assertEqual([("send", "coder", "coder_prompt.md")], ctx.runtime.calls)

    def test_enter_reviewing_builds_review_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertTrue((ctx.files.review_dir / "review_prompt.md").exists())
            self.assertEqual([("send", "reviewer", "review_prompt.md")], ctx.runtime.calls)

    def test_enter_completing_builds_confirmation_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature", with_docs=True)
            state = load_state(state_path)
            state["phase"] = "completing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertTrue((ctx.files.completion_dir / "confirmation_prompt.md").exists())
            self.assertEqual([("send", "reviewer", "confirmation_prompt.md")], ctx.runtime.calls)


if __name__ == "__main__":
    unittest.main()
