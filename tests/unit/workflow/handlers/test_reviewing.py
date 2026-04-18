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
from agentmux.workflow.phase_result import PhaseResult


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
        # Match production FeaturePaths.relative_path (str, forward slashes).
        self.files.relative_path = lambda p: p.relative_to(tmp_path).as_posix()
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
            "reviewer_nominations": [
                "reviewer_logic",
                "reviewer_quality",
                "reviewer_expert",
            ],
        }

        with patch.object(handler, "_request_summary", return_value=({}, None)):
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
        (specs,) = ctx.runtime.send_reviewers_many.call_args[0]
        expected_prompt = ctx.files.review_dir / "review_logic_prompt.md"
        for spec in specs:
            assert isinstance(spec.prompt_file, Path)
            assert spec.prompt_file.is_absolute(), (
                "ReviewerSpec.prompt_file must be absolute so send_prompt().resolve() "
                "points at the real file (not cwd-relative)."
            )
            assert spec.prompt_file == expected_prompt

    def test_enter_clears_stale_review_results_for_new_iteration(self, tmp_path):
        """When re-entering reviewing (not resume), stale review_results must not
        block new YAML ingestion.
        """
        ctx = FakeContext(tmp_path)
        handler = ReviewingHandler()

        state = {
            "last_event": "review_failed",  # not a resume path
            "review_iteration": 1,
            "reviewer_nominations": ["reviewer_logic", "reviewer_expert"],
            # stale results from prior iteration (logic failed previously)
            "review_results": {
                "reviewer_logic": {"verdict": "fail", "review_text": "old fail"},
                "reviewer_expert": {"verdict": "pass", "review_text": "old pass"},
            },
        }

        result = handler.enter(state, ctx)
        assert isinstance(result, PhaseResult)
        updates = result.updates
        # On a fresh entry (not resume), we expect a clean slate so new review
        # YAMLs can be ingested.
        assert updates["review_results"] == {}, (
            "stale review_results should be cleared for non-resume re-dispatch; "
            "otherwise _ingest_review_yaml will ignore new files."
        )


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

    def test_two_simultaneous_fails_aggregate_both_feedback(self, tmp_path):
        """Two reviewers fail in the same scan — fix_request contains both findings.

        Regression test for partial-aggregation bug: the previous code returned on
        the first 'fail' encountered in alphabetical order, dropping later fails'
        feedback. Here `expert` is processed first alphabetically; without the fix,
        `logic`'s findings would be silently lost.
        """
        ctx = FakeContext(tmp_path)
        ctx.write_review_yaml(
            "reviewer_expert", "fail", findings=["security regression"]
        )
        ctx.write_review_yaml("reviewer_logic", "fail", findings=["plan deviation"])

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {
                "reviewer_expert": "pending",
                "reviewer_logic": "pending",
            },
            "review_results": {},
        }
        event = MagicMock()

        _state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        content = ctx.files.fix_request.read_text()
        assert "security regression" in content
        assert "plan deviation" in content
        assert "reviewer_expert" in content
        assert "reviewer_logic" in content

    def test_pending_reviewer_pane_killed_on_early_fail(self, tmp_path):
        """When one reviewer fails while another is still pending, the pending
        reviewer's pane is torn down before transitioning to fixing — otherwise
        we leak a still-running reviewer process."""
        ctx = FakeContext(tmp_path)
        ctx.write_review_yaml("reviewer_expert", "fail", findings=["something bad"])
        # reviewer_logic is in active_reviews but never wrote a file

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "active_reviews": {
                "reviewer_expert": "pending",
                "reviewer_logic": "pending",
            },
            "review_results": {},
        }
        event = MagicMock()

        _state_update, next_phase = handler._handle_review(event, state, ctx)

        assert next_phase == "fixing"
        ctx.runtime.kill_primary.assert_any_call("reviewer_logic")

    def test_coder_panes_killed_on_review_pass(self, tmp_path):
        """When all reviewers pass and we request the summary, the coder pane(s)
        must be torn down (`finish_many` + `kill_primary`). Regression test for
        cleanup that existed on main but was dropped by the parallel-reviewer
        refactor.
        """
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
            patch("agentmux.workflow.handlers.reviewing.send_to_role"),
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            _state_update, _next_phase = handler._handle_review(event, state, ctx)

        ctx.runtime.finish_many.assert_any_call("coder")
        ctx.runtime.kill_primary.assert_any_call("coder")


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


class TestFollowupPromptAfterFix:
    """Post-fix follow-up prompt dispatch (Issue #119)."""

    def test_initial_prompt_used_on_first_iteration(self, tmp_path):
        """review_iteration == 0 → initial reviewer prompt (full context)."""
        ctx = FakeContext(tmp_path)

        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "last_event": "implementation_completed",
            "review_results": {},
        }
        handler.enter(state, ctx)

        prompt_path = ctx.files.review_dir / "review_logic_prompt.md"
        assert prompt_path.exists()
        prompt_content = prompt_path.read_text(encoding="utf-8")
        # Initial prompt includes architecture.md content via [[include:...]]
        assert "# Architecture" in prompt_content
        # Initial prompt identifies this role
        assert "Logic" in prompt_content or "logic" in prompt_content
        # Not a follow-up prompt
        assert "Follow-up" not in prompt_content

    def test_followup_prompt_used_after_fix(self, tmp_path):
        """review_iteration > 0 + prior archive exists → compact follow-up prompt."""
        ctx = FakeContext(tmp_path)

        # Previous iteration's archive — what the reviewer wrote last round.
        prev_archive = ctx.files.review_dir / "review_0_reviewer_logic.md"
        prev_archive.write_text(
            "# Previous findings\n\n- Logic bug in handler X\n",
            encoding="utf-8",
        )
        # Aggregated fix request the coder worked from.
        fix_request_path = ctx.files.review_dir / "fix_request.md"
        fix_request_path.write_text(
            "## Review: reviewer_logic (verdict: fail)\n\n- Logic bug in handler X\n",
            encoding="utf-8",
        )
        ctx.files.fix_request = fix_request_path

        handler = ReviewingHandler()
        state = {
            "review_iteration": 1,
            "last_event": "implementation_completed",
            "review_results": {},
        }
        handler.enter(state, ctx)

        prompt_path = ctx.files.review_dir / "review_logic_prompt.md"
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")

        # Must reference the previous review archive (content or path).
        assert "Logic bug in handler X" in content
        # Follow-up marker must be present.
        assert "Follow-up" in content
        # Must include the aggregated fix_request content.
        assert "Review: reviewer_logic" in content
        # Must NOT re-include the big initial-prompt fragments.
        assert "# Architecture" not in content
        assert "# Context" not in content
        # Iteration number is shown so the reviewer knows it's a re-review.
        assert "iteration" in content.lower()

        # Must include role arg in submit_review call (critical: omitting role
        # would cause the tool to read the wrong YAML on follow-up submissions).
        assert 'submit_review(role="reviewer_logic")' in content

    def test_followup_falls_back_to_initial_when_archive_missing(self, tmp_path):
        """Fallback: no prior archive → initial prompt is used (no crash)."""
        ctx = FakeContext(tmp_path)

        handler = ReviewingHandler()
        state = {
            "review_iteration": 1,
            "last_event": "implementation_completed",
            "review_results": {},
        }
        # No review_0_reviewer_logic.md exists.
        handler.enter(state, ctx)

        prompt_path = ctx.files.review_dir / "review_logic_prompt.md"
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        # Fallback to initial prompt (contains architecture.md include).
        assert "# Architecture" in content
        assert "Follow-up" not in content

    def test_resume_path_still_skips_completed(self, tmp_path):
        """Resume with all-completed reviews must NOT trigger a dispatch."""
        ctx = FakeContext(tmp_path)

        handler = ReviewingHandler()
        state = {
            "last_event": "resumed",
            "review_iteration": 1,
            "review_results": {
                "reviewer_logic": {"verdict": "pass", "review_text": "OK"},
            },
            "active_reviews": {"reviewer_logic": "completed"},
        }

        with patch.object(handler, "_request_summary", return_value={}):
            handler.enter(state, ctx)
        ctx.runtime.send_reviewers_many.assert_not_called()


class TestReviewMdMaterialization:
    """Tests for auto-materialization of review.md in _request_summary()."""

    def test_request_summary_materializes_review_md_when_missing(self, tmp_path):
        """_request_summary() writes review.md from review_results when absent."""
        ctx = FakeContext(tmp_path)
        handler = ReviewingHandler()
        state = {
            "review_iteration": 0,
            "reviewer_nominations": ["reviewer_logic"],
            "review_results": {},
        }
        review_results = {
            "reviewer_logic": {
                "verdict": "pass",
                "review_text": "verdict: pass\n\n## Summary\n\nAll good.\n",
            }
        }

        with (
            patch(
                "agentmux.workflow.handlers.reviewing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.reviewing.build_reviewer_summary_prompt",
                return_value="summary prompt",
            ),
            patch("agentmux.workflow.handlers.reviewing.send_to_role"),
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            handler._request_summary(state, ctx, review_results=review_results)

        review_md = ctx.files.review_dir / "review.md"
        assert review_md.exists(), "review.md must be created by _request_summary()"
        content = review_md.read_text(encoding="utf-8")
        assert "verdict: pass" in content
        assert "All good." in content

    def test_request_summary_does_not_overwrite_existing_review_md(self, tmp_path):
        """Legacy review.md written by single reviewer is preserved."""
        ctx = FakeContext(tmp_path)
        handler = ReviewingHandler()

        legacy_content = "verdict: pass\n\n## Summary\n\nLegacy reviewer wrote this.\n"
        (ctx.files.review_dir / "review.md").write_text(
            legacy_content, encoding="utf-8"
        )

        state = {
            "review_iteration": 0,
            "reviewer_nominations": ["reviewer_logic"],
            "review_results": {},
        }
        review_results = {
            "reviewer_logic": {
                "verdict": "pass",
                "review_text": "Some other content",
            }
        }

        with (
            patch(
                "agentmux.workflow.handlers.reviewing.write_prompt_file"
            ) as mock_write,
            patch(
                "agentmux.workflow.handlers.reviewing.build_reviewer_summary_prompt",
                return_value="summary prompt",
            ),
            patch("agentmux.workflow.handlers.reviewing.send_to_role"),
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            handler._request_summary(state, ctx, review_results=review_results)

        review_md = ctx.files.review_dir / "review.md"
        assert review_md.read_text(encoding="utf-8") == legacy_content, (
            "Existing review.md must not be overwritten by _request_summary()"
        )

    def test_parallel_reviewers_pass_generates_consolidated_review_md(self, tmp_path):
        """Both parallel reviewers passing triggers consolidated review.md."""
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
            patch("agentmux.workflow.handlers.reviewing.send_to_role"),
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            handler._handle_review(event, state, ctx)

        review_md = ctx.files.review_dir / "review.md"
        assert review_md.exists(), (
            "review.md must be generated after all parallel reviewers pass"
        )
        content = review_md.read_text(encoding="utf-8")
        assert "verdict: pass" in content

    def test_review_results_saved_to_state_on_all_pass(self, tmp_path):
        """When all reviewers pass, review_results are included in state updates."""
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
            patch("agentmux.workflow.handlers.reviewing.send_to_role"),
        ):
            mock_write.return_value = Path("/tmp/prompt.md")
            state_update, _next_phase = handler._handle_review(event, state, ctx)

        assert "review_results" in state_update, (
            "review_results must be saved to state when all reviewers pass"
        )
        assert "reviewer_logic" in state_update["review_results"]
        assert "reviewer_quality" in state_update["review_results"]
