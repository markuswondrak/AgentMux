"""Tests for reviewer routing — state-based select_reviewer_roles()."""

from agentmux.workflow.phase_helpers import select_reviewer_roles


class TestSelectReviewerRoles:
    """Test select_reviewer_roles() reads state["reviewer_nominations"]."""

    def test_missing_nominations_returns_logic(self):
        """Missing reviewer_nominations -> ["reviewer_logic"]."""
        state = {"phase": "reviewing"}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_empty_nominations_returns_logic(self):
        """Empty list -> ["reviewer_logic"]."""
        state = {"reviewer_nominations": []}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_none_nominations_returns_logic(self):
        """None value -> ["reviewer_logic"]."""
        state = {"reviewer_nominations": None}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_valid_single_preserved(self):
        """Valid single nomination preserved."""
        state = {"reviewer_nominations": ["reviewer_expert"]}
        assert select_reviewer_roles(state) == ["reviewer_expert"]

    def test_valid_list_preserved(self):
        """Valid list preserved as-is."""
        state = {"reviewer_nominations": ["reviewer_logic", "reviewer_quality"]}
        assert select_reviewer_roles(state) == ["reviewer_logic", "reviewer_quality"]

    def test_unknown_role_filtered_out(self):
        """Unknown roles are filtered out."""
        state = {"reviewer_nominations": ["reviewer_logic", "bogus", "reviewer_expert"]}
        assert select_reviewer_roles(state) == ["reviewer_logic", "reviewer_expert"]

    def test_all_unknown_returns_logic(self):
        """All unknown -> ["reviewer_logic"]."""
        state = {"reviewer_nominations": ["bogus", "fake"]}
        assert select_reviewer_roles(state) == ["reviewer_logic"]

    def test_non_list_returns_logic(self):
        """Non-list value -> ["reviewer_logic"]."""
        state = {"reviewer_nominations": "reviewer_logic"}
        assert select_reviewer_roles(state) == ["reviewer_logic"]


class TestSelectReviewerRolesIntegration:
    """Integration tests with state context."""

    def test_nomination_from_architect(self, tmp_path):
        """Nominations flow from state through selector."""
        state = {
            "phase": "architecting",
            "reviewer_nominations": ["reviewer_logic", "reviewer_expert"],
        }
        roles = select_reviewer_roles(state)
        assert roles == ["reviewer_logic", "reviewer_expert"]
