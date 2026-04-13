"""Unit-Tests für Verdict-Aggregation-Logik in reviewing Handler.

Tests für:
- Erstes "fail" triggert sofort fixing
- Alle "pass" triggert summary
- Mixed verdicts (fail nach einem pass) → fixing mit aggregiertem Feedback
- Parallele Reviews: wartet auf alle Reviewer bevor Transition
- Resume-Support — abgeschlossene Reviews nicht wiederholen
- review_yaml_has_verdict() mit role-spezifischen Dateien
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from agentmux.workflow.handlers.reviewing import ReviewingHandler
from agentmux.workflow.handoff_artifacts import review_yaml_has_verdict


class FakeContext:
    """Minimal fake PipelineContext for testing."""

    def __init__(self, tmp_path, max_review_iterations=2):
        self.feature_dir = tmp_path
        self.project_dir = tmp_path.parent / "project"
        self.project_dir.mkdir(parents=True, exist_ok=True)

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
        self.files.relative_path = lambda p: p.relative_to(tmp_path)
        self.files.project_dir = self.project_dir
        self.files.feature_dir = tmp_path

        # Create context.md required for reviewer prompts
        (tmp_path / "context.md").write_text("# Context", encoding="utf-8")
        # Create architecture file
        (tmp_path / "02_architecting").mkdir(parents=True, exist_ok=True)
        (tmp_path / "02_architecting" / "architecture.md").write_text(
            "# Architecture", encoding="utf-8"
        )
        # Create requirements file
        (tmp_path / "requirements.md").write_text("# Requirements", encoding="utf-8")

        self.runtime = MagicMock()
        self.max_review_iterations = max_review_iterations
        self.agents = {
            "reviewer_logic": MagicMock(),
            "reviewer_quality": MagicMock(),
            "reviewer_expert": MagicMock(),
        }

        # Write a default execution_plan.yaml
        plan_meta = {"review_strategy": {"severity": "medium", "focus": []}}
        (self.files.planning_dir / "execution_plan.yaml").write_text(
            yaml.dump(plan_meta, default_flow_style=False)
        )

    def write_review_yaml(self, role: str, verdict: str, findings: list | None = None):
        """Write a role-specific review YAML file with all required fields."""
        # Ensure findings are in dict format expected by generate_review_md
        formatted_findings = []
        if findings:
            for f in findings:
                if isinstance(f, str):
                    formatted_findings.append(
                        {
                            "location": "unknown",
                            "issue": f,
                            "severity": "high",
                            "recommendation": "Fix this issue",
                        }
                    )
                else:
                    formatted_findings.append(f)

        data = {
            "verdict": verdict,
            "summary": "Review summary" if findings else "No issues",
            "findings": formatted_findings,
            "commit_message": "feat: done" if verdict == "pass" else "",
        }
        (self.files.review_dir / f"review_{role}.yaml").write_text(
            yaml.dump(data, default_flow_style=False)
        )

    def write_review_md(self, content: str):
        self.files.review.write_text(content)


class TestVerdictAggregation:
    """Test verdict aggregation logic in _handle_review."""

    def test_fail_transitions_to_fixing(self, tmp_path):
        """First 'fail' verdict triggers transition to fixing."""
        ctx = FakeContext(tmp_path)
        role = "reviewer_logic"
        ctx.write_review_yaml(role, "fail", findings=["security issue found"])
        # Also create review.md for summary prompt include
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\nsecurity issue found", encoding="utf-8"
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        assert state_update["last_event"] is not None
        assert state_update["review_iteration"] == 1
        assert ctx.files.fix_request.exists()

    def test_pass_transitions_to_requesting_summary(self, tmp_path):
        """All 'pass' verdicts trigger summary request."""
        ctx = FakeContext(tmp_path)
        role = "reviewer_logic"
        ctx.write_review_yaml(role, "pass")
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: pass\n\n## Summary\n\nNo blocking issues.", encoding="utf-8"
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        with (
            patch(
                "agentmux.workflow.handlers.reviewing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.reviewing.build_reviewer_summary_prompt",
                return_value="summary prompt",
            ),
            patch("agentmux.workflow.handlers.reviewing.send_to_role") as mock_send,
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase is None  # stays in reviewing, awaiting summary
        assert state_update.get("awaiting_summary") is True
        mock_send.assert_called_once()

    def test_fail_at_max_iterations_transitions_to_completing(self, tmp_path):
        """Fail at max_review_iterations transitions to completing."""
        ctx = FakeContext(tmp_path, max_review_iterations=1)
        role = "reviewer_logic"
        ctx.write_review_yaml(role, "fail", findings=["still broken"])
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\nstill broken", encoding="utf-8"
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 1,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "completing"
        assert state_update["last_event"] is not None
        # fix_request should NOT be written at max iterations
        assert not ctx.files.fix_request.exists()

    def test_mixed_verdicts_fail_after_pass_transitions_to_fixing(self, tmp_path):
        """Mixed verdicts: fail after a pass → fixing with aggregated feedback."""
        ctx = FakeContext(tmp_path)
        role = "reviewer_logic"
        # Simulate: first reviewer passed, second fails
        ctx.write_review_yaml(role, "fail", findings=["new issue found after pass"])
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\nnew issue found after pass",
            encoding="utf-8",
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {
                "reviewer_quality": {"verdict": "pass", "review_text": "All good"}
            },
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        assert state_update["review_iteration"] == 1
        assert ctx.files.fix_request.exists()
        content = ctx.files.fix_request.read_text()
        assert "new issue found after pass" in content

    def test_review_archived_per_iteration(self, tmp_path):
        """Each review iteration is archived as review_N_<role>.md."""
        ctx = FakeContext(tmp_path)
        role = "reviewer_logic"
        ctx.write_review_yaml(role, "fail", findings=["iteration 0 issue"])
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: fail\n\n## Summary\n\niteration 0 issue", encoding="utf-8"
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        handler._handle_review(event, state, ctx)

        archive_path = ctx.files.review_dir / f"review_0_{role}.md"
        assert archive_path.exists()
        assert "iteration 0 issue" in archive_path.read_text()

    def test_invalid_verdict_returns_no_transition(self, tmp_path):
        """Invalid verdict results in no state transition."""
        ctx = FakeContext(tmp_path)
        role = "reviewer_logic"
        ctx.write_review_yaml(role, "maybe")
        (ctx.files.review_dir / "review.md").write_text(
            "verdict: unknown\n\n## Summary\n\nunclear", encoding="utf-8"
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {role: "pending"},
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase is None
        # Handler always returns state updates even for invalid verdicts
        assert "review_results" in state_update
        assert "active_reviews" in state_update


class TestResumeSupport:
    """Test resume support — completed reviews are not repeated."""

    def test_enter_skips_if_review_results_exist(self, tmp_path):
        """On resume, if review_results has entries, enter() does not re-dispatch."""
        ctx = FakeContext(tmp_path)

        handler = ReviewingHandler()
        state = {
            "last_event": "resumed",
            "review_results": {
                "reviewer_logic": {"verdict": "pass", "review_text": "OK"},
                "reviewer_quality": {"verdict": "pass", "review_text": "OK"},
                "reviewer_expert": {"verdict": "pass", "review_text": "OK"},
            },
            "active_reviews": {
                "reviewer_logic": "completed",
                "reviewer_quality": "completed",
                "reviewer_expert": "completed",
            },
        }

        with patch.object(handler, "_request_summary", return_value={}):
            handler.enter(state, ctx)
        # send_reviewers_many should NOT be called
        ctx.runtime.send_reviewers_many.assert_not_called()

    def test_enter_dispatches_when_no_review_results(self, tmp_path):
        """When no review_results exist, enter() dispatches reviewers."""
        ctx = FakeContext(tmp_path)

        handler = ReviewingHandler()
        state = {
            "last_event": "resumed",
            "review_results": {},
        }

        with patch.object(handler, "_request_summary", return_value={}):
            handler.enter(state, ctx)
        # send_reviewers_many SHOULD be called
        ctx.runtime.send_reviewers_many.assert_called_once()


class TestParallelVerdictFlow:
    """Tests for parallel review flow — multiple reviewers running simultaneously."""

    def test_first_pass_waits_for_second_reviewer(self, tmp_path):
        """When two reviewers are pending and only one passes, no transition yet."""
        ctx = FakeContext(tmp_path)
        # Only logic has submitted a review — quality is still pending
        ctx.write_review_yaml("reviewer_logic", "pass")

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {
                "reviewer_logic": "pending",
                "reviewer_quality": "pending",
            },
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase is None  # still waiting for reviewer_quality
        assert state_update["active_reviews"]["reviewer_logic"] == "completed"
        assert state_update["active_reviews"]["reviewer_quality"] == "pending"
        assert not ctx.files.fix_request.exists()

    def test_both_pass_simultaneously_triggers_summary(self, tmp_path):
        """When all reviewers pass in one scan, summary is triggered immediately."""
        ctx = FakeContext(tmp_path)
        ctx.write_review_yaml("reviewer_logic", "pass")
        ctx.write_review_yaml("reviewer_quality", "pass")

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {
                "reviewer_logic": "pending",
                "reviewer_quality": "pending",
            },
            "review_results": {},
        }
        event = MagicMock()

        with (
            patch(
                "agentmux.workflow.handlers.reviewing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.reviewing.build_reviewer_summary_prompt",
                return_value="summary prompt",
            ),
            patch("agentmux.workflow.handlers.reviewing.send_to_role") as mock_send,
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase is None  # stays in reviewing, awaiting summary
        assert state_update.get("awaiting_summary") is True
        mock_send.assert_called_once()

    def test_fail_aggregates_feedback_from_passing_reviewer_too(self, tmp_path):
        """When one reviewer passes and another fails, fix_request contains both."""
        ctx = FakeContext(tmp_path)
        ctx.write_review_yaml("reviewer_logic", "pass")
        ctx.write_review_yaml(
            "reviewer_quality", "fail", findings=["quality issue found"]
        )

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {
                "reviewer_logic": "pending",
                "reviewer_quality": "pending",
            },
            "review_results": {},
        }
        event = MagicMock()

        state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        assert ctx.files.fix_request.exists()
        content = ctx.files.fix_request.read_text()
        # fix_request must aggregate feedback from ALL completed reviewers
        assert "reviewer_logic" in content
        assert "reviewer_quality" in content
        assert "quality issue found" in content


class TestReviewYamlHasVerdictParallel:
    """Tests for review_yaml_has_verdict() with parallel role-specific files."""

    def test_returns_true_for_legacy_review_yaml(self, tmp_path):
        """review_yaml_has_verdict() still works for the legacy review.yaml path."""
        review_dir = tmp_path / "07_review"
        review_dir.mkdir()
        (review_dir / "review.yaml").write_text(
            yaml.dump({"verdict": "pass", "summary": "OK", "findings": []}),
            encoding="utf-8",
        )
        assert review_yaml_has_verdict(review_dir) is True

    def test_returns_true_for_role_specific_reviewer_file(self, tmp_path):
        """review_yaml_has_verdict() returns True for a role-specific file."""
        review_dir = tmp_path / "07_review"
        review_dir.mkdir()
        (review_dir / "review_reviewer_logic.yaml").write_text(
            yaml.dump({"verdict": "pass", "summary": "All good", "findings": []}),
            encoding="utf-8",
        )
        assert review_yaml_has_verdict(review_dir) is True

    def test_returns_true_for_fail_verdict_in_role_specific_file(self, tmp_path):
        """review_yaml_has_verdict() returns True for a fail verdict in role file."""
        review_dir = tmp_path / "07_review"
        review_dir.mkdir()
        (review_dir / "review_reviewer_expert.yaml").write_text(
            yaml.dump(
                {
                    "verdict": "fail",
                    "summary": "Issues found",
                    "findings": [{"issue": "bug", "recommendation": "fix"}],
                }
            ),
            encoding="utf-8",
        )
        assert review_yaml_has_verdict(review_dir) is True

    def test_returns_false_when_no_review_files_exist(self, tmp_path):
        """review_yaml_has_verdict() returns False when no review files exist."""
        review_dir = tmp_path / "07_review"
        review_dir.mkdir()
        assert review_yaml_has_verdict(review_dir) is False

    def test_returns_false_for_invalid_verdict_in_role_specific_file(self, tmp_path):
        """review_yaml_has_verdict() returns False for invalid verdict in role file."""
        review_dir = tmp_path / "07_review"
        review_dir.mkdir()
        (review_dir / "review_reviewer_logic.yaml").write_text(
            yaml.dump({"verdict": "maybe", "summary": "Unsure"}),
            encoding="utf-8",
        )
        assert review_yaml_has_verdict(review_dir) is False
