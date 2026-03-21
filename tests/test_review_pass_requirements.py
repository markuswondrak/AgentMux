from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
from src.handlers import handle_review_pass_docs, handle_review_pass_no_docs
from src.models import AgentConfig
from src.prompts import build_architect_prompt
from src.state import create_feature_files, load_state, write_state
from src.transitions import PipelineContext


class ReviewPassRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path, with_docs: bool) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(project_dir, feature_dir, "review pass handling", "session-x")

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
            panes={"architect": "%1", "coder": "%2", "docs": "%3", "designer": None},
            coder_panes={},
            agents=agents,
            max_review_iterations=3,
            session_name="session-x",
            prompts=prompts,
        )
        return ctx, files.state

    def test_review_prompt_uses_review_pass_without_review_file_on_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            files = create_feature_files(tmp_path / "project", tmp_path / "feature", "x", "session")

            prompt = build_architect_prompt(files, state_target="review_ready", is_review=True)

            self.assertIn("status to `review_pass` directly", prompt)
            self.assertIn("Do **not** write `review.md`", prompt)
            self.assertIn("`verdict: fail`", prompt)
            self.assertNotIn("`verdict: pass`", prompt)

    def test_review_pass_transitions_exist_before_review_ready(self) -> None:
        transitions = list(pipeline.TRANSITIONS)
        review_pass_idxs = [
            idx for idx, transition in enumerate(transitions) if transition.source == "review_pass"
        ]
        review_ready_idxs = [
            idx for idx, transition in enumerate(transitions) if transition.source == "review_ready"
        ]

        self.assertEqual(2, len(review_pass_idxs))
        self.assertTrue(review_ready_idxs)
        self.assertLess(max(review_pass_idxs), min(review_ready_idxs))

        descriptions = [transitions[idx].description for idx in review_pass_idxs]
        self.assertEqual(
            [
                "review_pass -> docs_update_requested",
                "review_pass -> completion_pending",
            ],
            descriptions,
        )

    def test_handle_review_pass_docs_skips_review_read_for_review_pass_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=True)

            state = load_state(state_path)
            state["status"] = "review_pass"
            write_state(state_path, state)

            if ctx.files.review.exists():
                ctx.files.review.unlink()

            with patch("src.handlers.parse_review_verdict", side_effect=AssertionError("unexpected parse")), patch(
                "src.handlers.send_prompt", return_value=None
            ), patch("src.handlers.park_agent_pane", return_value=None):
                handle_review_pass_docs(load_state(state_path), ctx)

            updated = load_state(state_path)
            self.assertEqual("docs_update_requested", updated["status"])
            self.assertEqual("docs", updated["active_role"])
            self.assertTrue((ctx.files.feature_dir / "docs_prompt.txt").exists())

    def test_handle_review_pass_no_docs_skips_review_read_for_review_pass_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = self._make_ctx(tmp_path / "feature", with_docs=False)

            state = load_state(state_path)
            state["status"] = "review_pass"
            write_state(state_path, state)

            if ctx.files.review.exists():
                ctx.files.review.unlink()

            with patch("src.handlers.parse_review_verdict", side_effect=AssertionError("unexpected parse")), patch(
                "src.handlers.send_prompt", return_value=None
            ), patch("src.handlers.park_agent_pane", return_value=None):
                handle_review_pass_no_docs(load_state(state_path), ctx)

            updated = load_state(state_path)
            self.assertEqual("completion_pending", updated["status"])
            self.assertEqual("architect", updated["active_role"])
            self.assertTrue((ctx.files.feature_dir / "confirmation_prompt.md").exists())


if __name__ == "__main__":
    unittest.main()
