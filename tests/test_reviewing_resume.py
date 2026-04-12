"""Tests for ReviewingHandler resume guard and per-iteration archive."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import ReviewingHandler
from agentmux.workflow.transitions import PipelineContext

PLANNING_DIR = SESSION_DIR_NAMES["planning"]


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

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

    def send_many(self, role: str, prompt_specs: list) -> None:
        self.calls.append(("send_many", role))

    def deactivate(self, role: str) -> None:
        self.calls.append(("deactivate", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))

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
        project_dir, feature_dir, "review handling", "session-x"
    )

    files.context.write_text("# Context", encoding="utf-8")
    files.architecture.parent.mkdir(parents=True, exist_ok=True)
    files.architecture.write_text("# Architecture", encoding="utf-8")
    files.requirements.write_text("# Requirements", encoding="utf-8")
    files.plan.parent.mkdir(parents=True, exist_ok=True)
    files.plan.write_text("# Plan", encoding="utf-8")

    agents = {
        "reviewer_logic": AgentConfig(
            role="reviewer_logic", cli="claude", model="sonnet", args=[]
        ),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    ctx = PipelineContext(
        files=files,
        runtime=FakeRuntime(),
        agents=agents,
        max_review_iterations=3,
        prompts={},
    )
    return ctx, files.state


class TestResumeGuard(unittest.TestCase):
    def test_resume_with_existing_review_does_not_delete_or_prompt(self) -> None:
        """On resume, if review.md exists, enter() leaves it and sends no prompt."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: fail\n- finding\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            self.assertEqual({}, result)
            self.assertTrue(ctx.files.review.exists(), "review.md must not be deleted")
            send_calls = [c for c in ctx.runtime.calls if c[0] == "send"]
            self.assertEqual([], send_calls, "no prompt should be sent on resume")

    def test_resume_with_existing_review_yaml_does_not_delete_or_prompt(self) -> None:
        """On resume, if review.yaml exists, enter() leaves it and sends no prompt."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review.yaml").write_text(
                yaml.dump(
                    {
                        "verdict": "fail",
                        "summary": "Needs fixes",
                        "findings": [
                            {
                                "issue": "Missing validation",
                                "recommendation": "Add the missing check.",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            self.assertEqual({}, result)
            self.assertTrue((ctx.files.review_dir / "review.yaml").exists())
            send_calls = [c for c in ctx.runtime.calls if c[0] == "send"]
            self.assertEqual([], send_calls, "no prompt should be sent on resume")

    def test_resume_without_review_sends_prompt(self) -> None:
        """On resume, if review.md does not exist, enter() proceeds normally."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            # No review.md created

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            send_calls = [c for c in ctx.runtime.calls if c[0] == "send"]
            self.assertTrue(
                len(send_calls) > 0, "prompt must be sent when no review.md"
            )

    def test_fresh_entry_deletes_stale_review(self) -> None:
        """On fresh entry (not resume), a stale review.md is deleted."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.review.write_text("verdict: pass\n", encoding="utf-8")

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "implementation_completed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertFalse(
                ctx.files.review.exists(), "stale review.md must be deleted"
            )

    def test_fresh_entry_deletes_stale_review_yaml(self) -> None:
        """On fresh entry, a stale review.yaml is also deleted."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            ctx.files.review.parent.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review.yaml").write_text(
                yaml.dump(
                    {
                        "verdict": "pass",
                        "summary": "Looks good",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "implementation_completed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertFalse(
                (ctx.files.review_dir / "review.yaml").exists(),
                "stale review.yaml must be deleted",
            )


class TestReviewArchive(unittest.TestCase):
    _FAIL_PAYLOAD: dict = {
        "verdict": "fail",
        "summary": "Issues found in implementation.",
        "findings": [
            {
                "location": "src/x.py:1",
                "issue": "missing validation",
                "severity": "high",
                "recommendation": "Add input validation.",
            }
        ],
    }
    _PASS_PAYLOAD: dict = {
        "verdict": "pass",
        "summary": "All checks pass.",
        "findings": [],
        "commit_message": "feat: implementation complete",
    }

    def _dispatch_review(
        self,
        ctx: PipelineContext,
        state_path: Path,
        payload: dict,
        iteration: int = 0,
    ) -> tuple[dict, str | None]:
        ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        (ctx.files.review_dir / "review.yaml").write_text(
            yaml.dump(payload, default_flow_style=False),
            encoding="utf-8",
        )

        state = load_state(state_path)
        state["phase"] = "reviewing"
        state["review_iteration"] = iteration
        write_state(state_path, state)

        handler = ReviewingHandler()
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        return handler.handle_event(event, load_state(state_path), ctx)

    def test_verdict_fail_creates_archive_and_keeps_review_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(ctx, state_path, self._FAIL_PAYLOAD, iteration=0)

            archive = ctx.files.review_dir / "review_0.md"
            self.assertTrue(archive.exists(), "review_0.md archive must be created")
            self.assertIn("verdict: fail", archive.read_text(encoding="utf-8"))
            self.assertTrue(ctx.files.review.exists(), "review.md must still exist")

    def test_verdict_fail_second_iteration_archives_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(ctx, state_path, self._FAIL_PAYLOAD, iteration=1)

            archive = ctx.files.review_dir / "review_1.md"
            self.assertTrue(archive.exists(), "review_1.md archive must be created")

    def test_verdict_pass_creates_archive_and_keeps_review_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(ctx, state_path, self._PASS_PAYLOAD, iteration=0)

            archive = ctx.files.review_dir / "review_0.md"
            self.assertTrue(
                archive.exists(), "review_0.md archive must be created on pass"
            )
            self.assertTrue(
                ctx.files.review.exists(), "review.md must still exist on pass"
            )

    def test_archive_contains_same_content_as_review_md(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(ctx, state_path, self._FAIL_PAYLOAD, iteration=2)

            archive = ctx.files.review_dir / "review_2.md"
            review_md = ctx.files.review_dir / "review.md"
            self.assertTrue(archive.exists(), "archive must be created")
            self.assertTrue(review_md.exists(), "review.md must be created")
            self.assertEqual(
                review_md.read_text(encoding="utf-8"),
                archive.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
