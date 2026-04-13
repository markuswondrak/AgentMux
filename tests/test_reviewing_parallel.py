"""Tests for ReviewingHandler parallel reviewer dispatch and verdict aggregation."""

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
    review_strategy: dict | None = None,
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

    # Create execution_plan.yaml with review_strategy
    planning_dir = feature_dir / PLANNING_DIR
    planning_dir.mkdir(parents=True, exist_ok=True)
    plan_data: dict = {}
    if review_strategy is not None:
        plan_data["review_strategy"] = review_strategy
    (planning_dir / "execution_plan.yaml").write_text(
        yaml.dump(plan_data, default_flow_style=False), encoding="utf-8"
    )

    agents = {
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
    return ctx, files.state


class TestParallelReviewerDispatch(unittest.TestCase):
    """Test that enter() dispatches multiple reviewers in parallel."""

    def test_enter_dispatches_single_reviewer_for_low_severity(self) -> None:
        """low severity → only quality reviewer dispatched."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "low", "focus": []},
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "implementation_completed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            # enter() returns state updates (active_reviews, review_results)
            self.assertIn("active_reviews", result)
            self.assertIn("review_results", result)
            self.assertEqual({"reviewer_quality": "pending"}, result["active_reviews"])

            # Should have called send_reviewers_many with quality role
            dispatch_calls = [
                c for c in ctx.runtime.calls if c[0] == "send_reviewers_many"
            ]
            self.assertEqual(len(dispatch_calls), 1)
            self.assertEqual(["reviewer_quality"], dispatch_calls[0][1])

    def test_enter_dispatches_multiple_reviewers_for_expert(self) -> None:
        """medium severity + security focus → expert reviewer dispatched."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "medium", "focus": ["security"]},
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "implementation_completed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            self.assertIn("active_reviews", result)
            self.assertEqual({"reviewer_expert": "pending"}, result["active_reviews"])

            dispatch_calls = [
                c for c in ctx.runtime.calls if c[0] == "send_reviewers_many"
            ]
            self.assertEqual(len(dispatch_calls), 1)
            self.assertEqual(["reviewer_expert"], dispatch_calls[0][1])

    def test_enter_initializes_empty_review_results(self) -> None:
        """enter() should initialize empty review_results dict."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "low", "focus": []},
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "implementation_completed"
            write_state(state_path, state)

            handler = ReviewingHandler()
            result = handler.enter(load_state(state_path), ctx)

            self.assertEqual({}, result.get("review_results", {}))


class TestVerdictAggregation(unittest.TestCase):
    """Test _handle_review() with multi-reviewer verdict aggregation."""

    _FAIL_PAYLOAD: dict = {
        "verdict": "fail",
        "summary": "Issues found.",
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

    def _setup_review(
        self,
        ctx: PipelineContext,
        state_path: Path,
        reviewer_role: str,
        payload: dict,
        active_reviews: dict,
        review_results: dict,
        iteration: int = 0,
    ) -> tuple[dict, str | None]:
        """Helper to set up state and dispatch a review for a specific role."""
        ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
        # Write review.yaml for the specific role
        (ctx.files.review_dir / f"review_{reviewer_role}.yaml").write_text(
            yaml.dump(payload, default_flow_style=False),
            encoding="utf-8",
        )
        # Also create review.md for the summary prompt include
        (ctx.files.review_dir / "review.md").write_text(
            f"verdict: {payload['verdict']}\n\n## Summary\n\n{payload['summary']}\n",
            encoding="utf-8",
        )

        state = load_state(state_path)
        state["phase"] = "reviewing"
        state["review_iteration"] = iteration
        state["active_reviews"] = active_reviews
        state["review_results"] = review_results
        write_state(state_path, state)

        handler = ReviewingHandler()
        event = WorkflowEvent(kind="review", payload={"payload": {}})
        return handler.handle_event(event, load_state(state_path), ctx)

    def test_pass_records_result_and_triggers_summary_for_single_reviewer(self) -> None:
        """Pass verdict with single reviewer → summary triggered."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "medium", "focus": ["security"]},
            )
            result_updates, next_phase = self._setup_review(
                ctx,
                state_path,
                reviewer_role="reviewer_expert",
                payload=self._PASS_PAYLOAD,
                active_reviews={"reviewer_expert": "pending"},
                review_results={},
            )

            # Single reviewer, all pass → summary triggered
            self.assertEqual("review_passed", result_updates.get("last_event"))
            self.assertTrue(result_updates.get("awaiting_summary"))

    def test_all_pass_triggers_summary(self) -> None:
        """All reviewers pass → _request_summary() triggered."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "medium", "focus": ["security"]},
            )
            # Simulate reviewer_expert already passed
            result_updates, next_phase = self._setup_review(
                ctx,
                state_path,
                reviewer_role="reviewer_expert",
                payload=self._PASS_PAYLOAD,
                active_reviews={"reviewer_expert": "pending"},
                review_results={},
            )

            self.assertEqual("review_passed", result_updates.get("last_event"))
            self.assertTrue(result_updates.get("awaiting_summary"))

    def test_fail_triggers_fixing_with_aggregated_feedback(self) -> None:
        """Fail verdict → EVENT_REVIEW_FAILED with aggregated feedback."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "medium", "focus": ["security"]},
            )
            result_updates, next_phase = self._setup_review(
                ctx,
                state_path,
                reviewer_role="reviewer_expert",
                payload=self._FAIL_PAYLOAD,
                active_reviews={"reviewer_expert": "pending"},
                review_results={},
            )

            self.assertEqual("review_failed", result_updates.get("last_event"))
            self.assertEqual("fixing", next_phase)
            # fix_request.md should be written
            self.assertTrue(ctx.files.fix_request.exists())
            fix_content = ctx.files.fix_request.read_text(encoding="utf-8")
            self.assertIn("missing validation", fix_content)


class TestResumeSupport(unittest.TestCase):
    """Test resume behavior for parallel reviewers."""

    def test_resume_skips_completed_reviewers(self) -> None:
        """Resume skips reviewers already present in review_results."""
        with tempfile.TemporaryDirectory() as td:
            ctx, state_path = _make_ctx(
                Path(td) / "feature",
                review_strategy={"severity": "medium", "focus": ["security"]},
            )
            # Create review.md so _request_summary doesn't fail on include
            ctx.files.review_dir.mkdir(parents=True, exist_ok=True)
            (ctx.files.review_dir / "review.md").write_text(
                "verdict: pass\n\n## Summary\n\nOK\n", encoding="utf-8"
            )
            state = load_state(state_path)
            state["phase"] = "reviewing"
            state["last_event"] = "resumed"
            state["active_reviews"] = {"reviewer_expert": "completed"}
            state["review_results"] = {
                "reviewer_expert": {"verdict": "pass", "summary": "OK"}
            }
            write_state(state_path, state)

            handler = ReviewingHandler()
            handler.enter(load_state(state_path), ctx)

            # No new dispatch should happen
            dispatch_calls = [
                c for c in ctx.runtime.calls if c[0] == "send_reviewers_many"
            ]
            self.assertEqual([], dispatch_calls)


if __name__ == "__main__":
    unittest.main()
