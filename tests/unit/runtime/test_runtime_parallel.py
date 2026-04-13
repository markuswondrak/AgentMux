"""Unit-Tests für send_reviewers_many() — Pane-Erstellung, Rückgabe.

Tests für:
- Erstellt Panes für alle Specs
- Gibt korrekte {role: pane_id} Zuordnung zurück
- Zeigt alle Panes parallel
- Leere Liste wird gracefully behandelt
"""

from pathlib import Path
from unittest.mock import patch

from agentmux.runtime import ReviewerSpec, TmuxAgentRuntime


def _fake_agents():
    """Create minimal agents config for testing."""
    from agentmux.runtime import AgentConfig

    return {
        "reviewer_logic": AgentConfig(
            role="reviewer_logic", cli="claude", model="sonnet", args=[]
        ),
        "reviewer_quality": AgentConfig(
            role="reviewer_quality", cli="claude", model="sonnet", args=[]
        ),
        "reviewer_expert": AgentConfig(
            role="reviewer_expert", cli="claude", model="sonnet", args=[]
        ),
    }


class FakeZone:
    """Fake content_zone for testing."""

    def __init__(self, session_name):
        self.session_name = session_name
        self.parallel_shows = []
        self.visible = {}

    def show_parallel(self, pane_ids):
        self.parallel_shows.append(list(pane_ids))

    def hide(self, pane_id):
        pass


class TestSendReviewersMany:
    """Test send_reviewers_many() pane creation and return values."""

    def test_creates_panes_for_all_specs(self, tmp_path):
        """send_reviewers_many creates panes for each ReviewerSpec."""
        feature_dir = tmp_path
        prompt_a = feature_dir / "reviewer_logic.md"
        prompt_b = feature_dir / "reviewer_quality.md"
        prompt_a.write_text("logic review", encoding="utf-8")
        prompt_b.write_text("quality review", encoding="utf-8")
        zone = FakeZone("session-x")
        created_panes = []
        sent_prompts = []

        def fake_create(
            session_name, role, agents, project_dir, trust_snippet, **kwargs
        ):
            pane_id = f"%reviewer_{role}"
            created_panes.append((role, pane_id))
            return (pane_id, 12345)

        def fake_send_prompt(pane_id, prompt_file):
            sent_prompts.append((pane_id, prompt_file.name))

        with (
            patch("agentmux.runtime.tmux_pane_exists", return_value=False),
            patch("agentmux.runtime.create_agent_pane", side_effect=fake_create),
            patch("agentmux.runtime.send_prompt", side_effect=fake_send_prompt),
            patch("agentmux.runtime.set_pane_identity", return_value=None),
        ):
            runtime = TmuxAgentRuntime(
                feature_dir=feature_dir,
                project_dir=Path("/project"),
                session_name="session-x",
                agents=_fake_agents(),
                primary_panes={"architect": "%1"},
                zone=zone,
            )
            result = runtime.send_reviewers_many(
                [
                    ReviewerSpec(
                        role="reviewer_logic",
                        prompt_file=prompt_a,
                        display_label="Logic Review",
                    ),
                    ReviewerSpec(
                        role="reviewer_quality",
                        prompt_file=prompt_b,
                    ),
                ]
            )

        # Returns dict mapping role -> pane_id
        assert result == {
            "reviewer_logic": "%reviewer_reviewer_logic",
            "reviewer_quality": "%reviewer_reviewer_quality",
        }
        # Parallel show called for all panes
        assert zone.parallel_shows == [
            ["%reviewer_reviewer_logic", "%reviewer_reviewer_quality"]
        ]
        # Prompts sent to correct panes
        assert {
            ("%reviewer_reviewer_logic", "reviewer_logic.md"),
            ("%reviewer_reviewer_quality", "reviewer_quality.md"),
        } == set(sent_prompts)

    def test_empty_specs_returns_empty_dict(self, tmp_path):
        """send_reviewers_many with empty list returns {}."""
        feature_dir = tmp_path
        zone = FakeZone("session-x")

        runtime = TmuxAgentRuntime(
            feature_dir=feature_dir,
            project_dir=Path("/project"),
            session_name="session-x",
            agents=_fake_agents(),
            primary_panes={"architect": "%1"},
            zone=zone,
        )
        result = runtime.send_reviewers_many([])
        assert result == {}

    def test_three_roles_creates_all_panes(self, tmp_path):
        """send_reviewers_many handles all 3 reviewer roles."""
        feature_dir = tmp_path
        prompt_logic = feature_dir / "logic.md"
        prompt_quality = feature_dir / "quality.md"
        prompt_expert = feature_dir / "expert.md"
        prompt_logic.write_text("logic", encoding="utf-8")
        prompt_quality.write_text("quality", encoding="utf-8")
        prompt_expert.write_text("expert", encoding="utf-8")
        zone = FakeZone("session-x")
        sent_prompts = []

        def fake_create(
            session_name, role, agents, project_dir, trust_snippet, **kwargs
        ):
            return (f"%reviewer_{role}", 12345)

        def fake_send_prompt(pane_id, prompt_file):
            sent_prompts.append((pane_id, prompt_file.name))

        with (
            patch("agentmux.runtime.tmux_pane_exists", return_value=False),
            patch("agentmux.runtime.create_agent_pane", side_effect=fake_create),
            patch("agentmux.runtime.send_prompt", side_effect=fake_send_prompt),
            patch("agentmux.runtime.set_pane_identity", return_value=None),
        ):
            runtime = TmuxAgentRuntime(
                feature_dir=feature_dir,
                project_dir=Path("/project"),
                session_name="session-x",
                agents=_fake_agents(),
                primary_panes={"architect": "%1"},
                zone=zone,
            )
            result = runtime.send_reviewers_many(
                [
                    ReviewerSpec(role="reviewer_logic", prompt_file=prompt_logic),
                    ReviewerSpec(role="reviewer_quality", prompt_file=prompt_quality),
                    ReviewerSpec(role="reviewer_expert", prompt_file=prompt_expert),
                ]
            )

        assert len(result) == 3
        assert "reviewer_logic" in result
        assert "reviewer_quality" in result
        assert "reviewer_expert" in result
        assert len(sent_prompts) == 3

    def test_parallel_panes_tracked_in_runtime(self, tmp_path):
        """send_reviewers_many tracks panes in parallel_panes dict."""
        feature_dir = tmp_path
        prompt_a = feature_dir / "a.md"
        prompt_a.write_text("a", encoding="utf-8")
        zone = FakeZone("session-x")

        def fake_create(
            session_name, role, agents, project_dir, trust_snippet, **kwargs
        ):
            return (f"%reviewer_{role}", 12345)

        def fake_send_prompt(pane_id, prompt_file):
            pass

        with (
            patch("agentmux.runtime.tmux_pane_exists", return_value=False),
            patch("agentmux.runtime.create_agent_pane", side_effect=fake_create),
            patch("agentmux.runtime.send_prompt", side_effect=fake_send_prompt),
            patch("agentmux.runtime.set_pane_identity", return_value=None),
        ):
            runtime = TmuxAgentRuntime(
                feature_dir=feature_dir,
                project_dir=Path("/project"),
                session_name="session-x",
                agents=_fake_agents(),
                primary_panes={"architect": "%1"},
                zone=zone,
            )
            runtime.send_reviewers_many(
                [
                    ReviewerSpec(role="reviewer_logic", prompt_file=prompt_a),
                    ReviewerSpec(role="reviewer_quality", prompt_file=prompt_a),
                ]
            )

        assert "reviewer_logic" in runtime.parallel_panes
        assert "reviewer_quality" in runtime.parallel_panes

    def test_unknown_role_is_skipped_without_raising(self, tmp_path):
        """send_reviewers_many skips specs with unknown roles (no KeyError)."""
        feature_dir = tmp_path
        prompt_a = feature_dir / "a.md"
        prompt_a.write_text("logic review", encoding="utf-8")
        zone = FakeZone("session-x")

        def fake_create(
            session_name, role, agents, project_dir, trust_snippet, **kwargs
        ):
            return (f"%reviewer_{role}", 12345)

        with (
            patch("agentmux.runtime.tmux_pane_exists", return_value=False),
            patch("agentmux.runtime.create_agent_pane", side_effect=fake_create),
            patch("agentmux.runtime.send_prompt"),
            patch("agentmux.runtime.set_pane_identity", return_value=None),
        ):
            runtime = TmuxAgentRuntime(
                feature_dir=feature_dir,
                project_dir=Path("/project"),
                session_name="session-x",
                agents=_fake_agents(),
                primary_panes={},
                zone=zone,
            )
            # reviewer_unknown is not in agents dict — must not raise KeyError
            result = runtime.send_reviewers_many(
                [
                    ReviewerSpec(role="reviewer_logic", prompt_file=prompt_a),
                    ReviewerSpec(role="reviewer_unknown", prompt_file=prompt_a),
                ]
            )

        # Only the known role should be returned
        assert "reviewer_logic" in result
        assert "reviewer_unknown" not in result
