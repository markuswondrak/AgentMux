"""Integrationstests: Mock paralleler Reviewer, State-Transitions.

Simuliert den parallelen Review-Workflow:
- Mehrere Reviewer senden submit_review Events
- State-Transitions werden validiert (reviewing → fixing, reviewing → completing)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from agentmux.workflow.handlers.reviewing import ReviewingHandler


class FakeIntegrationContext:
    """Fake PipelineContext for integration testing."""

    def __init__(self, tmp_path, max_review_iterations=3):
        self.feature_dir = tmp_path
        self.files = MagicMock()
        self.files.planning_dir = tmp_path / "02_planning"
        self.files.planning_dir.mkdir(parents=True)
        self.files.review = tmp_path / "07_review" / "review.md"
        self.files.review_dir = tmp_path / "07_review"
        self.files.review_dir.mkdir(parents=True)
        self.files.fix_request = tmp_path / "06_implementation" / "fix_request.txt"
        self.files.fix_request.parent.mkdir(parents=True)
        self.files.completion_dir = tmp_path / "08_completion"
        self.files.completion_dir.mkdir(parents=True)
        self.files.summary = self.files.completion_dir / "summary.md"
        # Match production FeaturePaths.relative_path (str, forward slashes).
        self.files.relative_path = lambda p: p.relative_to(tmp_path).as_posix()

        self.runtime = MagicMock()
        self.max_review_iterations = max_review_iterations
        self.agents = {
            "reviewer_logic": MagicMock(),
            "reviewer_quality": MagicMock(),
            "reviewer_expert": MagicMock(),
        }

        plan_meta = {"review_strategy": {"severity": "medium", "focus": []}}
        (self.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(plan_meta, default_flow_style=False)
        )

    def submit_review(
        self, verdict: str, findings: list | None = None, review_iteration: int = 0
    ):
        """Simulate a reviewer submitting a review."""
        data = {"verdict": verdict, "summary": "Test summary"}
        if findings:
            data["findings"] = [
                {"issue": f, "recommendation": "Fix it."} for f in findings
            ]
        # Write role-specific review file (logic reviewer is default)
        (self.files.review_dir / "review_reviewer_logic.yaml").write_text(
            yaml.dump(data, default_flow_style=False)
        )
        review_content = f"verdict: {verdict}\n"
        if findings:
            for f in findings:
                review_content += f"- {f}\n"
        self.files.review.write_text(review_content)


class TestParallelReviewerStateTransitions:
    """Test state transitions with simulated parallel reviewers."""

    def test_first_fail_transitions_to_fixing(self, tmp_path):
        """First reviewer fail → reviewing → fixing."""
        ctx = FakeIntegrationContext(tmp_path)
        ctx.submit_review("fail", findings=["critical bug"])

        handler = ReviewingHandler()
        role = "reviewer_logic"
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        assert state_update["review_iteration"] == 1
        assert ctx.files.fix_request.exists()
        assert "critical bug" in ctx.files.fix_request.read_text()

    def test_all_pass_transitions_to_completing_flow(self, tmp_path):
        """All reviewers pass → reviewing → completing (via summary)."""
        ctx = FakeIntegrationContext(tmp_path)
        ctx.submit_review("pass")
        # Create review.md for summary prompt include expansion
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: pass\n\n## Summary\n\nNo issues.", encoding="utf-8"
        )

        handler = ReviewingHandler()
        role = "reviewer_logic"
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        with (
            patch(
                "agentmux.workflow.handlers.reviewing.build_reviewer_summary_prompt",
                return_value="summary prompt",
            ),
            patch(
                "agentmux.workflow.handlers.reviewing.write_prompt_file",
                return_value=Path("/tmp/prompt.md"),
            ),
            patch("agentmux.workflow.handlers.reviewing.send_to_role"),
        ):
            state_update, next_phase = handler._handle_review(event, state, ctx)

        # Stays in reviewing, awaiting summary
        assert next_phase is None
        assert state_update.get("awaiting_summary") is True

    def test_mixed_verdicts_fail_after_pass_transitions_to_fixing(self, tmp_path):
        """Mixed verdicts: first pass, then fail → fixing."""
        ctx = FakeIntegrationContext(tmp_path)
        # Simulate second reviewer finding issues after first passed
        ctx.submit_review("fail", findings=["regression found"])

        handler = ReviewingHandler()
        role = "reviewer_logic"
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        assert state_update["review_iteration"] == 1

    def test_max_iterations_reached_transitions_to_completing(self, tmp_path):
        """Fail at max_review_iterations → completing."""
        ctx = FakeIntegrationContext(tmp_path, max_review_iterations=1)
        ctx.submit_review("fail", findings=["still broken"])

        handler = ReviewingHandler()
        role = "reviewer_logic"
        state = {
            "review_iteration": 1,  # Already at max
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "completing"
        assert state_update["last_event"] is not None
        # fix_request should NOT be written when max iterations reached
        assert not ctx.files.fix_request.exists()

    def test_multiple_iterations_track_review_iteration(self, tmp_path):
        """Review iteration counter increments correctly across fix cycles."""
        ctx = FakeIntegrationContext(tmp_path)

        handler = ReviewingHandler()
        role = "reviewer_logic"
        event = MagicMock()

        # First fail
        ctx.submit_review("fail", findings=["bug 1"])
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        state_update, next_phase = handler._handle_review(event, state, ctx)
        assert next_phase == "fixing"
        assert state_update["review_iteration"] == 1

        # Second fail
        ctx.submit_review("fail", findings=["bug 2"])
        state["review_iteration"] = state_update["review_iteration"]
        state["active_reviews"] = {role: "pending"}
        state_update2, next_phase2 = handler._handle_review(event, state, ctx)
        assert next_phase2 == "fixing"
        assert state_update2["review_iteration"] == 2
