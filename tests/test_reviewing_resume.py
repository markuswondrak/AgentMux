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
from agentmux.workflow.handlers.base import PhaseResult
from agentmux.workflow.transitions import PipelineContext


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

    def send_reviewers_many(self, reviewer_specs: list) -> dict[str, str]:
        """Fake send_reviewers_many — records call and returns mock pane mapping."""
        roles = [spec.role for spec in reviewer_specs]
        self.calls.append(("send_reviewers_many", roles))
        return {role: f"%pane_{role}" for role in roles}

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


def _make_ctx(
    feature_dir: Path,
    *,
    reviewer_nominations: list[str] | None = None,
    max_review_iterations: int = 3,
) -> tuple[PipelineContext, Path]:
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

    # Create execution_plan.yaml (no review_strategy needed anymore)
    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "execution_plan.yaml").write_text(
        yaml.dump({}, default_flow_style=False), encoding="utf-8"
    )

    agents: dict[str, AgentConfig] = {
        "reviewer_logic": AgentConfig(
            role="reviewer_logic", cli="claude", model="sonnet", args=[]
        ),
        "reviewer_quality": AgentConfig(
            role="reviewer_quality", cli="claude", model="sonnet", args=[]
        ),
        "reviewer_expert": AgentConfig(
            role="reviewer_expert", cli="claude", model="sonnet", args=[]
        ),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    ctx = PipelineContext(
        files=files,
        runtime=FakeRuntime(),
        agents=agents,
        max_review_iterations=max_review_iterations,
        prompts={},
    )
    # Store nominations in state
    if reviewer_nominations:
        # We'll set this in the state after loading
        pass
    return ctx, files.state


class TestResumeGuard(unittest.TestCase):
    def test_resume_with_existing_review_results_does_not_redispatch(self) -> None:
        """On resume, if review_results has entry, reviewer is not re-dispatched."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                reviewer_nominations=["reviewer_logic"],
            )
            # Create review.md so _request_summary doesn't fail on include
            ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review.md").write_text(
                "verdict: pass\n\n## Summary\n\nOK\n", encoding="utf-8"
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            state["reviewer_nominations"] = ["reviewer_logic"]
            state["review_results"] = {
                "reviewer_logic": {"verdict": "pass", "review_text": "OK"}
            }
            state["active_reviews"] = {"reviewer_logic": "completed"}
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            # No new dispatch should happen
            dispatch_calls = [
                c for c in ctx.runtime.calls if c[0] == "send_reviewers_many"
            ]
            self.assertEqual([], dispatch_calls)
            # Should be PhaseResult with summary request
            self.assertIsInstance(result, PhaseResult)
            self.assertEqual("review_passed", result.updates.get("last_event"))

    def test_resume_without_review_results_sends_prompt(self) -> None:
        """On resume, if review_results is empty, enter() proceeds normally."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                reviewer_nominations=["reviewer_logic"],
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            state["reviewer_nominations"] = ["reviewer_logic"]
            # No review_results set
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            # Should dispatch the logic reviewer
            dispatch_calls = [
                c for c in ctx.runtime.calls if c[0] == "send_reviewers_many"
            ]
            self.assertEqual(len(dispatch_calls), 1)
            self.assertEqual(["reviewer_logic"], dispatch_calls[0][1])

    def test_fresh_entry_clears_stale_review_yaml_for_pending_roles(self) -> None:
        """Fresh entry deletes stale review_<role>.yaml for pending roles."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                reviewer_nominations=["reviewer_quality"],
            )
            ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review_reviewer_quality.yaml").write_text(
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
            state["reviewer_nominations"] = ["reviewer_quality"]
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertFalse(
                (ctx.files.review_dir / "review_reviewer_quality.yaml").exists(),
                "stale review_reviewer_quality.yaml must be deleted",
            )

    def test_resume_ingests_pre_existing_yaml(self) -> None:
        """On resume, valid review_<role>.yaml without state entry is ingested."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                reviewer_nominations=["reviewer_logic"],
            )
            ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review_reviewer_logic.yaml").write_text(
                yaml.dump(
                    {
                        "verdict": "pass",
                        "summary": "All good",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (ctx.files.review_dir / "review.md").write_text(
                "verdict: pass\n\n## Summary\n\nOK\n", encoding="utf-8"
            )

            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            state["reviewer_nominations"] = ["reviewer_logic"]
            # No review_results — should ingest from YAML
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            # Should have ingested the verdict
            self.assertIn("reviewer_logic", result.updates.get("review_results", {}))
            # Should not re-dispatch
            dispatch_calls = [
                c for c in ctx.runtime.calls if c[0] == "send_reviewers_many"
            ]
            self.assertEqual([], dispatch_calls)

    def test_enter_returns_phase_result_no_tuple_crash(self) -> None:
        """enter() always returns PhaseResult, never tuple[dict, str|None]."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                reviewer_nominations=["reviewer_logic"],
            )
            ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review.md").write_text(
                "verdict: pass\n\n## Summary\n\nOK\n", encoding="utf-8"
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            state["reviewer_nominations"] = ["reviewer_logic"]
            state["review_results"] = {
                "reviewer_logic": {"verdict": "pass", "review_text": "OK"}
            }
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            self.assertIsInstance(result, PhaseResult)
            # result.updates must be a dict, result.next_phase may be None
            self.assertIsInstance(result.updates, dict)


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
        reviewer_role: str,
        payload: dict,
        iteration: int = 0,
        active_reviews: dict | None = None,
        review_results: dict | None = None,
    ) -> tuple[dict, str | None]:
        """Helper to set up state and dispatch a review for a specific role."""
        ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        # Write review.yaml for the specific role
        (ctx.files.review_dir / f"review_{reviewer_role}.yaml").write_text(
            yaml.dump(payload, default_flow_style=False),
            encoding="utf-8",
        )

        state = load_state(state_path)
        state["phase"] = "reviewing"
        state["review_iteration"] = iteration
        state["active_reviews"] = active_reviews or {reviewer_role: "pending"}
        state["review_results"] = review_results or {}
        write_state(state_path, state)

        handler = ReviewingHandler()
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        return handler.handle_event(event, load_state(state_path), ctx)

    def test_verdict_fail_creates_archive_and_keeps_review_yaml(self) -> None:
        role = "reviewer_quality"
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(
                ctx, state_path, role, self._FAIL_PAYLOAD, iteration=0
            )

            archive = ctx.files.review_dir / f"review_0_{role}.md"
            self.assertTrue(archive.exists(), f"{archive.name} archive must be created")
            self.assertIn("verdict: fail", archive.read_text(encoding="utf-8"))
            self.assertTrue(
                (ctx.files.review_dir / f"review_{role}.yaml").exists(),
                f"review_{role}.yaml must still exist",
            )

    def test_verdict_fail_second_iteration_archives_correctly(self) -> None:
        role = "reviewer_quality"
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(
                ctx, state_path, role, self._FAIL_PAYLOAD, iteration=1
            )

            archive = ctx.files.review_dir / f"review_1_{role}.md"
            self.assertTrue(archive.exists(), f"{archive.name} archive must be created")

    def test_verdict_pass_creates_archive_and_keeps_review_yaml(self) -> None:
        role = "reviewer_quality"
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            # Create review.md so _request_summary doesn't fail on include
            ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review.md").write_text(
                "verdict: pass\n\n## Summary\n\nOK\n",
                encoding="utf-8",
            )
            self._dispatch_review(
                ctx, state_path, role, self._PASS_PAYLOAD, iteration=0
            )

            archive = ctx.files.review_dir / f"review_0_{role}.md"
            self.assertTrue(
                archive.exists(), f"{archive.name} archive must be created on pass"
            )
            self.assertTrue(
                (ctx.files.review_dir / f"review_{role}.yaml").exists(),
                f"review_{role}.yaml must still exist on pass",
            )

    def test_archive_contains_same_content_as_review_md(self) -> None:
        role = "reviewer_quality"
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(Path(td) / "feature")
            self._dispatch_review(
                ctx, state_path, role, self._FAIL_PAYLOAD, iteration=2
            )

            archive = ctx.files.review_dir / f"review_2_{role}.md"
            _ = ctx.files.review_dir / f"review_{role}.yaml"
            self.assertTrue(archive.exists(), "archive must be created")
            # Verify archive contains the review content from the YAML
            archive_text = archive.read_text(encoding="utf-8")
            self.assertIn("missing validation", archive_text)


if __name__ == "__main__":
    unittest.main()
