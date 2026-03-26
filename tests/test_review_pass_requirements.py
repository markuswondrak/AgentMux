from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentmux.models import AgentConfig, SESSION_DIR_NAMES
from agentmux.phases import PHASES, get_phase
from agentmux.prompts import build_reviewer_prompt
from agentmux.state import create_feature_files, load_state, write_state
from agentmux.transitions import PipelineContext

PLANNING_DIR = SESSION_DIR_NAMES["planning"]


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


class ReviewPassRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path, with_docs: bool) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(project_dir, feature_dir, "review handling", "session-x")

        prompts = {"architect": feature_dir / PLANNING_DIR / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(prompt.name, encoding="utf-8")

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
            prompts=prompts,
        )
        return ctx, files.state

    def _write_plan_meta(self, ctx: PipelineContext, *, needs_docs: bool, doc_files: list[str] | None = None) -> None:
        ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
        plan_meta = {
            "needs_design": False,
            "needs_docs": needs_docs,
            "doc_files": doc_files if doc_files is not None else [],
        }
        (ctx.files.planning_dir / "plan_meta.json").write_text(
            json.dumps(plan_meta) + "\n",
            encoding="utf-8",
        )

    def test_reviewer_prompt_requires_review_md_for_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            files = create_feature_files(tmp_path / "project", tmp_path / "feature", "x", "session")

            prompt = build_reviewer_prompt(files, is_review=True)

            self.assertIn("Always write `06_review/review.md`", prompt)
            self.assertIn("verdict: pass", prompt)
            self.assertIn("verdict: fail", prompt)
            self.assertIn("Do not update `state.json`", prompt)

    def test_reviewing_phase_on_enter_sends_prompt_to_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=False)
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: pass\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.on_enter(load_state(state_path), ctx)

            self.assertIn(("send", "reviewer", "review_prompt.md"), ctx.runtime.calls)
            self.assertFalse(ctx.files.review.exists())

    def test_reviewing_phase_is_registered(self) -> None:
        self.assertIn("reviewing", PHASES)

    def test_handle_review_passed_moves_to_documenting_when_docs_agent_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=True)
            self._write_plan_meta(ctx, needs_docs=True, doc_files=["docs/file-protocol.md"])

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "review_passed", ctx)

            updated = load_state(state_path)
            self.assertEqual("documenting", updated["phase"])
            self.assertEqual("review_passed", updated["last_event"])

    def test_handle_review_passed_moves_to_completing_when_docs_not_required(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=True)
            self._write_plan_meta(ctx, needs_docs=False, doc_files=[])

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "review_passed", ctx)

            updated = load_state(state_path)
            self.assertEqual("completing", updated["phase"])
            self.assertEqual("review_passed", updated["last_event"])

    def test_handle_review_passed_raises_when_docs_required_but_docs_agent_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=False)
            self._write_plan_meta(ctx, needs_docs=True, doc_files=["README.md"])

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            with self.assertRaises(RuntimeError):
                phase.handle_event(load_state(state_path), "review_passed", ctx)

    def test_handle_review_failed_moves_to_fixing_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=False)
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
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

    def test_documenting_phase_completion_kills_docs_pane_and_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=True)

            state = load_state(state_path)
            state["phase"] = "documenting"
            write_state(state_path, state)

            ctx.files.docs_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.docs_dir / "docs_done").touch()

            phase = get_phase(load_state(state_path))
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("docs_completed", event)
            phase.handle_event(load_state(state_path), "docs_completed", ctx)

            updated = load_state(state_path)
            self.assertEqual("completing", updated["phase"])
            self.assertEqual("docs_completed", updated["last_event"])
            self.assertIn(("kill_primary", "docs"), ctx.runtime.calls)
            self.assertNotIn(("deactivate", "docs"), ctx.runtime.calls)


if __name__ == "__main__":
    unittest.main()
