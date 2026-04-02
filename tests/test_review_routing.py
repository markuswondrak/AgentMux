"""Tests for reviewer routing logic based on plan_meta review_strategy."""

from agentmux.workflow.phase_helpers import select_reviewer_type


class TestSelectReviewerType:
    """Test select_reviewer_type() function covering all routing rules."""

    def test_missing_review_strategy_returns_logic(self):
        """Missing review_strategy key -> returns "logic" (backward compat)."""
        plan_meta = {
            "needs_design": False,
            "needs_docs": True,
            "doc_files": ["docs/file-protocol.md"],
        }
        assert select_reviewer_type(plan_meta) == "logic"

    def test_empty_plan_meta_returns_logic(self):
        """Empty plan_meta dict -> returns "logic"."""
        plan_meta = {}
        assert select_reviewer_type(plan_meta) == "logic"

    def test_low_severity_with_any_focus_returns_quality(self):
        """low severity with any focus -> returns "quality"."""
        plan_meta = {
            "review_strategy": {
                "severity": "low",
                "focus": ["accessibility", "performance"],
            }
        }
        assert select_reviewer_type(plan_meta) == "quality"

    def test_low_severity_empty_focus_returns_quality(self):
        """low severity with empty focus -> returns "quality"."""
        plan_meta = {
            "review_strategy": {
                "severity": "low",
                "focus": [],
            }
        }
        assert select_reviewer_type(plan_meta) == "quality"

    def test_medium_severity_empty_focus_returns_logic(self):
        """medium severity with empty focus -> returns "logic"."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": [],
            }
        }
        assert select_reviewer_type(plan_meta) == "logic"

    def test_medium_severity_accessibility_focus_returns_logic(self):
        """medium severity with ["accessibility"] -> returns "logic"."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": ["accessibility"],
            }
        }
        assert select_reviewer_type(plan_meta) == "logic"

    def test_medium_severity_security_focus_returns_expert(self):
        """medium severity with ["security"] -> returns "expert"."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": ["security"],
            }
        }
        assert select_reviewer_type(plan_meta) == "expert"

    def test_medium_severity_performance_focus_returns_expert(self):
        """medium severity with ["performance"] -> returns "expert"."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": ["performance"],
            }
        }
        assert select_reviewer_type(plan_meta) == "expert"

    def test_high_severity_empty_focus_returns_logic(self):
        """high severity with empty focus -> returns "logic"."""
        plan_meta = {
            "review_strategy": {
                "severity": "high",
                "focus": [],
            }
        }
        assert select_reviewer_type(plan_meta) == "logic"

    def test_high_severity_security_focus_returns_expert(self):
        """high severity with ["security"] -> returns "expert"."""
        plan_meta = {
            "review_strategy": {
                "severity": "high",
                "focus": ["security"],
            }
        }
        assert select_reviewer_type(plan_meta) == "expert"

    def test_high_severity_performance_focus_returns_expert(self):
        """high severity with ["performance"] -> returns "expert"."""
        plan_meta = {
            "review_strategy": {
                "severity": "high",
                "focus": ["performance"],
            }
        }
        assert select_reviewer_type(plan_meta) == "expert"


class TestSelectReviewerTypeEdgeCases:
    """Test edge cases for select_reviewer_type() function."""

    def test_invalid_severity_value_defaults_to_logic(self):
        """Invalid severity value -> defaults to "logic"."""
        plan_meta = {
            "review_strategy": {
                "severity": "invalid",
                "focus": [],
            }
        }
        assert select_reviewer_type(plan_meta) == "logic"

    def test_focus_as_non_list_handles_gracefully(self):
        """Focus as non-list value -> handles gracefully."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": "security",
            }
        }
        assert select_reviewer_type(plan_meta) == "logic"

    def test_unknown_focus_values_route_based_on_severity(self):
        """Unknown focus values -> routes based on severity alone."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": ["unknown", "another_unknown"],
            }
        }
        assert select_reviewer_type(plan_meta) == "logic"


class TestReviewRoutingIntegration:
    """Integration tests for review routing in workflow context."""

    def test_backward_compatibility_no_review_strategy(self, tmp_path):
        """Session without review_strategy uses logic reviewer (backward compat)."""

        # Create a mock planning directory without review_strategy
        planning_dir = tmp_path / "02_planning"
        planning_dir.mkdir(parents=True)
        plan_meta = {
            "needs_design": False,
            "needs_docs": False,
            "doc_files": [],
        }
        import json

        (planning_dir / "plan_meta.json").write_text(json.dumps(plan_meta))

        # Verify routing defaults to logic
        from agentmux.workflow.phase_helpers import load_plan_meta, select_reviewer_type

        loaded_meta = load_plan_meta(planning_dir)
        reviewer_type = select_reviewer_type(loaded_meta)
        assert reviewer_type == "logic"

    def test_planning_to_reviewing_transition_with_various_plan_meta(self, tmp_path):
        """Test transition with various plan_meta configurations."""
        import json

        from agentmux.workflow.phase_helpers import load_plan_meta, select_reviewer_type

        test_cases = [
            ({"severity": "low", "focus": []}, "quality"),
            ({"severity": "medium", "focus": []}, "logic"),
            ({"severity": "medium", "focus": ["security"]}, "expert"),
            ({"severity": "high", "focus": ["performance"]}, "expert"),
        ]

        for idx, (review_strategy, expected_type) in enumerate(test_cases):
            planning_dir = tmp_path / f"02_planning_{idx}_{expected_type}"
            planning_dir.mkdir(parents=True)
            plan_meta = {"review_strategy": review_strategy}
            (planning_dir / "plan_meta.json").write_text(json.dumps(plan_meta))

            loaded_meta = load_plan_meta(planning_dir)
            reviewer_type = select_reviewer_type(loaded_meta)
            assert reviewer_type == expected_type, f"Failed for {review_strategy}"
