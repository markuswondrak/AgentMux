"""Unit-Tests für state-based select_reviewer_roles()."""

from agentmux.workflow.phase_helpers import select_reviewer_roles


class TestSelectReviewerRolesStateBased:
    """Test all state-based nomination scenarios."""

    def test_missing_nominations_defaults_to_logic(self):
        """Missing reviewer_nominations -> ["reviewer_logic"] (default)."""
        state = {"phase": "reviewing"}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_empty_nominations_defaults_to_logic(self):
        """Empty list -> ["reviewer_logic"]."""
        assert select_reviewer_roles({"reviewer_nominations": []}) == ["reviewer_logic"]

    def test_single_nomination_preserved(self):
        """Single valid nomination preserved."""
        state = {"reviewer_nominations": ["reviewer_quality"]}
        assert select_reviewer_roles(state) == ["reviewer_quality"]

    def test_multiple_nominations_preserved(self):
        """Multiple valid nominations preserved."""
        state = {"reviewer_nominations": ["reviewer_logic", "reviewer_expert"]}
        assert select_reviewer_roles(state) == ["reviewer_logic", "reviewer_expert"]

    def test_unknown_filtered(self):
        """Unknown roles filtered out, valid kept."""
        state = {
            "reviewer_nominations": ["reviewer_logic", "invalid", "reviewer_quality"]
        }
        assert select_reviewer_roles(state) == ["reviewer_logic", "reviewer_quality"]

    def test_all_unknown_returns_logic(self):
        """If all filtered, fallback to logic."""
        state = {"reviewer_nominations": ["invalid", "fake"]}
        assert select_reviewer_roles(state) == ["reviewer_logic"]


class TestSelectReviewerRolesEdgeCases:
    """Edge cases for select_reviewer_roles()."""

    def test_none_value_returns_logic(self):
        """None value -> ["reviewer_logic"]."""
        state = {"reviewer_nominations": None}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_string_value_returns_logic(self):
        """String (non-list) -> ["reviewer_logic"]."""
        state = {"reviewer_nominations": "reviewer_expert"}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_empty_state_returns_logic(self):
        """Empty state -> ["reviewer_logic"]."""
        assert select_reviewer_roles({}) == ["reviewer_logic"]
