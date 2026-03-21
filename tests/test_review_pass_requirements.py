from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.models import AgentConfig
from src.phases import PHASES, get_phase
from src.prompts import build_architect_prompt
from src.state import create_feature_files, load_state, write_state
from src.transitions import PipelineContext


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

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


class ReviewPassRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path, with_docs: bool) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(project_dir, feature_dir, "review handling", "session-x")

        prompts = {"architect": feature_dir / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.write_text(prompt.name, encoding="utf-8")

        agents = {
            "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
        }
        if with_docs:
            agents["docs"] = AgentConfig(role="docs", cli="codex", model="gpt-5.3-codex", args=[])

        ctx = PipelineContext(
            files=files,
            runtime=FakeRuntime(),
            agents=agents,
            max_review_iterations=3,
            prompts=prompts,
        )
        return ctx, files.state

    def test_review_prompt_requires_review_md_for_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            files = create_feature_files(tmp_path / "project", tmp_path / "feature", "x", "session")

            prompt = build_architect_prompt(files, is_review=True)

            self.assertIn("Always write `review.md`", prompt)
            self.assertIn("verdict: pass", prompt)
            self.assertIn("verdict: fail", prompt)
            self.assertIn("Do not update `state.json`", prompt)

    def test_reviewing_phase_is_registered(self) -> None:
        self.assertIn("reviewing", PHASES)

    def test_handle_review_passed_moves_to_documenting_when_docs_agent_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=True)

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "review_passed", ctx)

            updated = load_state(state_path)
            self.assertEqual("documenting", updated["phase"])
            self.assertEqual("review_passed", updated["last_event"])

    def test_handle_review_passed_moves_to_completing_without_docs_agent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=False)

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "review_passed", ctx)

            updated = load_state(state_path)
            self.assertEqual("completing", updated["phase"])
            self.assertEqual("review_passed", updated["last_event"])

    def test_handle_review_failed_moves_to_fixing_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=False)
            ctx.files.review.write_text("verdict: fail\n- finding\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["review_iteration"] = 1
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "review_failed", ctx)

            updated = load_state(state_path)
            self.assertEqual("fixing", updated["phase"])
            self.assertEqual(2, updated["review_iteration"])
            self.assertTrue(ctx.files.fix_request.exists())


if __name__ == "__main__":
    unittest.main()
