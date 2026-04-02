from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PHASE_HANDLERS, ReviewingHandler
from agentmux.workflow.prompts import build_reviewer_prompt
from agentmux.workflow.transitions import PipelineContext

PLANNING_DIR = SESSION_DIR_NAMES["planning"]


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def send(
        self, role: str, prompt_file: Path, display_label: str | None = None
    ) -> None:
        self.calls.append(("send", role, prompt_file.name, display_label))

    def send_many(self, role: str, prompt_specs: list[object]) -> None:
        self.calls.append(
            (
                "send_many",
                role,
                [
                    Path(getattr(item, "prompt_file", item)).name
                    for item in prompt_specs
                ],
            )
        )

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
    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(
            project_dir, feature_dir, "review handling", "session-x"
        )

        prompts = {"architect": feature_dir / PLANNING_DIR / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(prompt.name, encoding="utf-8")

        agents = {
            "architect": AgentConfig(
                role="architect", cli="claude", model="opus", args=[]
            ),
            "reviewer": AgentConfig(
                role="reviewer", cli="claude", model="sonnet", args=[]
            ),
            "coder": AgentConfig(
                role="coder", cli="codex", model="gpt-5.3-codex", args=[]
            ),
        }

        ctx = PipelineContext(
            files=files,
            runtime=FakeRuntime(),
            agents=agents,
            max_review_iterations=3,
            prompts=prompts,
        )
        return ctx, files.state

    def test_reviewer_prompt_requires_review_md_for_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            files = create_feature_files(
                tmp_path / "project", tmp_path / "feature", "x", "session"
            )

            prompt = build_reviewer_prompt(files, is_review=True)

            self.assertIn("Always write `06_review/review.md`", prompt)
            self.assertIn("verdict: pass", prompt)
            self.assertIn("verdict: fail", prompt)
            self.assertIn("Do not update `state.json`", prompt)

    def test_reviewing_phase_on_enter_sends_prompt_to_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: pass\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertIn(
                (
                    "send",
                    "reviewer_logic",
                    "review_logic_prompt.md",
                    "[reviewer_logic]",
                ),
                ctx.runtime.calls,
            )
            self.assertFalse(ctx.files.review.exists())

    def test_reviewing_phase_is_registered(self) -> None:
        self.assertIn("reviewing", PHASE_HANDLERS)

    def test_handle_review_passed_moves_to_completing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature")
            # Create the review.md file with verdict: pass
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: pass\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            handler = ReviewingHandler()
            event = WorkflowEvent(
                kind="file.created",
                path="06_review/review.md",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("completing", next_phase)
            self.assertEqual("review_passed", updates.get("last_event"))
            self.assertIn(("finish_many", "coder"), ctx.runtime.calls)
            self.assertIn(("kill_primary", "coder"), ctx.runtime.calls)

    def test_handle_review_passed_ignores_docs_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature")
            ctx.files.planning_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.planning_dir / "plan_meta.json").write_text(
                (
                    '{"needs_design": false, "needs_docs": true, '
                    '"doc_files": ["docs/file-protocol.md"]}'
                ),
                encoding="utf-8",
            )
            # Create the review.md file with verdict: pass
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: pass\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            write_state(state_path, state)

            handler = ReviewingHandler()
            event = WorkflowEvent(
                kind="file.created",
                path="06_review/review.md",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("completing", next_phase)
            self.assertEqual("review_passed", updates.get("last_event"))

    def test_handle_review_failed_moves_to_fixing_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: fail\n- finding\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["review_iteration"] = 1
            write_state(state_path, state)

            handler = ReviewingHandler()
            event = WorkflowEvent(
                kind="file.created",
                path="06_review/review.md",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("fixing", next_phase)
            self.assertEqual(2, updates.get("review_iteration"))
            self.assertTrue(ctx.files.fix_request.exists())


if __name__ == "__main__":
    unittest.main()
