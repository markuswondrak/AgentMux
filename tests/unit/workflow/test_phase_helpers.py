"""Unit-Tests für select_reviewer_roles() — alle 5 Kombinationen + Defaults.

Diese Tests ergänzen die bestehenden Tests in tests/test_review_routing.py
und dokumentieren explizit die 5 Severity/Focus-Kombinationen aus dem Plan.
"""

from agentmux.workflow.phase_helpers import select_reviewer_roles


class TestSelectReviewerRolesAllCombinations:
    """Test all 5 severity/focus combinations from the plan."""

    def test_missing_review_strategy_defaults_to_logic(self):
        """Missing review_strategy -> ["logic"] (default)."""
        plan_meta = {"needs_design": False, "needs_docs": True}
        assert select_reviewer_roles(plan_meta) == ["logic"]

    def test_empty_plan_meta_defaults_to_logic(self):
        """Empty plan_meta -> ["logic"]."""
        assert select_reviewer_roles({}) == ["logic"]

    def test_low_severity_returns_quality(self):
        """low severity -> ["quality"] regardless of focus."""
        plan_meta = {"review_strategy": {"severity": "low", "focus": ["accessibility"]}}
        assert select_reviewer_roles(plan_meta) == ["quality"]

    def test_medium_severity_no_security_performance_returns_logic(self):
        """medium severity + no security/performance -> ["logic"]."""
        plan_meta = {
            "review_strategy": {"severity": "medium", "focus": ["accessibility"]}
        }
        assert select_reviewer_roles(plan_meta) == ["logic"]

    def test_medium_severity_with_security_returns_expert(self):
        """medium severity + security focus -> ["expert"]."""
        plan_meta = {"review_strategy": {"severity": "medium", "focus": ["security"]}}
        assert select_reviewer_roles(plan_meta) == ["expert"]

    def test_medium_severity_with_performance_returns_expert(self):
        """medium severity + performance focus -> ["expert"]."""
        plan_meta = {
            "review_strategy": {"severity": "medium", "focus": ["performance"]}
        }
        assert select_reviewer_roles(plan_meta) == ["expert"]

    def test_high_severity_no_security_performance_returns_logic(self):
        """high severity + no security/performance -> ["logic"]."""
        plan_meta = {
            "review_strategy": {"severity": "high", "focus": ["accessibility"]}
        }
        assert select_reviewer_roles(plan_meta) == ["logic"]

    def test_high_severity_with_security_returns_expert(self):
        """high severity + security focus -> ["expert"]."""
        plan_meta = {"review_strategy": {"severity": "high", "focus": ["security"]}}
        assert select_reviewer_roles(plan_meta) == ["expert"]

    def test_high_severity_with_performance_returns_expert(self):
        """high severity + performance focus -> ["expert"]."""
        plan_meta = {"review_strategy": {"severity": "high", "focus": ["performance"]}}
        assert select_reviewer_roles(plan_meta) == ["expert"]


class TestSelectReviewerRolesEdgeCases:
    """Edge cases for select_reviewer_roles()."""

    def test_invalid_severity_defaults_to_logic(self):
        """Invalid severity value -> ["logic"]."""
        plan_meta = {"review_strategy": {"severity": "unknown", "focus": []}}
        assert select_reviewer_roles(plan_meta) == ["logic"]

    def test_non_list_focus_handles_gracefully(self):
        """Focus as non-list value -> handles gracefully, returns ["logic"]."""
        plan_meta = {"review_strategy": {"severity": "medium", "focus": "security"}}
        assert select_reviewer_roles(plan_meta) == ["logic"]

    def test_unknown_focus_values_routes_by_severity(self):
        """Unknown focus values -> routes based on severity alone."""
        plan_meta = {
            "review_strategy": {
                "severity": "medium",
                "focus": ["unknown", "another_unknown"],
            }
        }
        assert select_reviewer_roles(plan_meta) == ["logic"]
