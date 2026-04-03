"""Tests for splitting architecting and planning phases.

This test file validates the foundation changes needed to support
the new planner agent role and architecture.md file.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import _make_runtime_files
from agentmux.shared.models import (
    PREFERENCE_PROPOSAL_SOURCES,
    PROMPT_AGENT_ROLES,
    SESSION_DIR_NAMES,
    RuntimeFiles,
)


class TestPlannerRole(unittest.TestCase):
    """Test that planner role is properly added to role constants."""

    def test_planner_in_prompt_agent_roles(self) -> None:
        """Planner should be in PROMPT_AGENT_ROLES after architect."""
        self.assertIn("planner", PROMPT_AGENT_ROLES)
        # Verify position: architect should come before planner
        architect_idx = PROMPT_AGENT_ROLES.index("architect")
        planner_idx = PROMPT_AGENT_ROLES.index("planner")
        self.assertGreater(planner_idx, architect_idx)

    def test_planner_in_preference_proposal_sources(self) -> None:
        """Planner should be able to propose preferences."""
        self.assertIn("planner", PREFERENCE_PROPOSAL_SOURCES)


class TestArchitectingPhase(unittest.TestCase):
    """Test that architecting phase is added to session directory names."""

    def test_architecting_in_session_dir_names(self) -> None:
        """Architecting phase should be mapped to 02_planning directory."""
        self.assertIn("architecting", SESSION_DIR_NAMES)
        self.assertEqual(SESSION_DIR_NAMES["architecting"], "02_planning")


class TestRuntimeFilesArchitecture(unittest.TestCase):
    """Test that RuntimeFiles includes architecture.md path."""

    def test_runtime_files_has_architecture_field(self) -> None:
        """RuntimeFiles dataclass should have an architecture field."""
        # Check that architecture is a field on RuntimeFiles
        fields = RuntimeFiles.__dataclass_fields__
        self.assertIn("architecture", fields)

    def test_make_runtime_files_sets_architecture_path(self) -> None:
        """_make_runtime_files should set architecture to planning_dir /
        architecture.md."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            feature_dir.mkdir()

            files = _make_runtime_files(project_dir, feature_dir)

            expected_path = feature_dir / "02_planning" / "architecture.md"
            self.assertEqual(files.architecture, expected_path)

    def test_architecture_path_in_planning_dir(self) -> None:
        """Architecture path should be in the planning directory."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            feature_dir.mkdir()

            files = _make_runtime_files(project_dir, feature_dir)

            # Verify it's in the planning directory subtree
            self.assertTrue(str(files.architecture).startswith(str(files.planning_dir)))
            self.assertEqual(files.architecture.name, "architecture.md")


class TestPlannerPromptTemplates(unittest.TestCase):
    """Test that planner prompt templates exist and are correctly structured."""

    def setUp(self) -> None:
        self.project_root = Path(__file__).parent.parent
        self.agents_dir = self.project_root / "src" / "agentmux" / "prompts" / "agents"
        self.commands_dir = (
            self.project_root / "src" / "agentmux" / "prompts" / "commands"
        )

    def test_planner_agent_prompt_exists(self) -> None:
        """Planner agent prompt template should exist."""
        planner_prompt = self.agents_dir / "planner.md"
        self.assertTrue(
            planner_prompt.exists(),
            f"Planner agent prompt not found at {planner_prompt}",
        )

    def test_planner_agent_prompt_not_empty(self) -> None:
        """Planner agent prompt should not be empty."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            self.assertTrue(len(content.strip()) > 0, "Planner agent prompt is empty")

    def test_planner_agent_prompt_has_role_definition(self) -> None:
        """Planner agent prompt should define the planner role."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            # Should identify as planner agent
            self.assertIn("planner", content.lower())

    def test_planner_agent_prompt_references_architecture(self) -> None:
        """Planner agent prompt should reference architecture document."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            # Should reference architecture.md or architecture document
            has_architecture_ref = (
                "architecture.md" in content
                or "architecture document" in content.lower()
                or "02_planning/architecture.md" in content
            )
            self.assertTrue(
                has_architecture_ref,
                "Planner prompt should reference architecture document",
            )

    def test_planner_respects_architecture_constraint(self) -> None:
        """Planner should have constraint to NOT modify architecture."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8").lower()
            # Should have constraint about not modifying architecture
            has_constraint = (
                "verändere niemals die architektur" in content
                or "do not modify the architecture" in content
                or "never modify the architecture" in content
                or "architecture as absolute truth" in content
                or "take the design as absolute truth" in content
            )
            self.assertTrue(
                has_constraint,
                "Planner must NOT modify architecture - take it as absolute truth",
            )

    def test_planner_agent_includes_context_include(self) -> None:
        """Planner agent prompt should include context.md."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            self.assertIn("[[include:context.md]]", content)

    def test_planner_agent_does_not_include_requirements(self) -> None:
        """Planner should NOT include requirements.md - architecture is truth."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            # Planner should NOT include requirements.md - architecture is truth
            self.assertNotIn("[[include:requirements.md]]", content)

    def test_planner_agent_includes_architecture_include(self) -> None:
        """Planner agent prompt should include architecture.md."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            self.assertIn("[[include:02_planning/architecture.md]]", content)

    def test_planner_agent_includes_execution_plan_json(self) -> None:
        """Planner agent prompt should mention execution_plan.json creation."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            self.assertIn("execution_plan.json", content)

    def test_planner_agent_includes_plan_markdown(self) -> None:
        """Planner agent prompt should mention plan.md creation."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            self.assertIn("plan.md", content)

    def test_planner_agent_includes_tasks_files(self) -> None:
        """Planner agent prompt should mention tasks file creation."""
        planner_prompt = self.agents_dir / "planner.md"
        if planner_prompt.exists():
            content = planner_prompt.read_text(encoding="utf-8")
            has_tasks_ref = "tasks_1.md" in content or "tasks_<N>.md" in content
            self.assertTrue(has_tasks_ref, "Planner should create tasks files")


if __name__ == "__main__":
    unittest.main()


class TestArchitectingPhaseHandler(unittest.TestCase):
    """Test that architecting phase handler exists and works correctly."""

    def test_architecting_handler_exists(self) -> None:
        """ArchitectingHandler should exist in handlers module."""
        from agentmux.workflow.handlers import PHASE_HANDLERS

        self.assertIn("architecting", PHASE_HANDLERS)

    def test_architecting_handler_has_enter_method(self) -> None:
        """ArchitectingHandler should have enter method."""
        from agentmux.workflow.handlers import PHASE_HANDLERS

        handler = PHASE_HANDLERS.get("architecting")
        if handler:
            self.assertTrue(hasattr(handler, "enter"))
            self.assertTrue(callable(getattr(handler, "enter", None)))

    def test_architecting_handler_has_handle_event_method(self) -> None:
        """ArchitectingHandler should have handle_event method."""
        from agentmux.workflow.handlers import PHASE_HANDLERS

        handler = PHASE_HANDLERS.get("architecting")
        if handler:
            self.assertTrue(hasattr(handler, "handle_event"))
            self.assertTrue(callable(getattr(handler, "handle_event", None)))

    def test_architecting_transitions_to_planning(self) -> None:
        """Architecting phase should transition to planning when
        architecture.md is written."""
        # This tests the transition logic in the handler
        from agentmux.workflow.handlers import PHASE_HANDLERS

        handler = PHASE_HANDLERS.get("architecting")
        self.assertIsNotNone(handler, "ArchitectingHandler must exist")

    def test_architect_owns_research_in_architecting_phase(self) -> None:
        """During architecting phase, architect should own research tasks."""
        from agentmux.workflow.orchestrator import PipelineOrchestrator

        orchestrator = PipelineOrchestrator()
        # Test that architect is the owner during planning/architecting phases
        state = {"phase": "architecting"}
        owner = orchestrator._determine_research_owner(state, "code-researcher")
        self.assertEqual(owner, "architect")


class TestPlanningPhaseUsesPlanner(unittest.TestCase):
    """Test that planning phase uses planner agent."""

    def test_planning_handler_uses_planner_agent(self) -> None:
        """PlanningHandler should send prompts to planner agent."""
        from agentmux.workflow.handlers import PlanningHandler

        # The handler should use planner agent
        handler = PlanningHandler()
        self.assertTrue(hasattr(handler, "enter"))

    def test_build_planner_prompt_exists(self) -> None:
        """build_planner_prompt function should exist."""
        from agentmux.workflow.prompts import build_planner_prompt

        # Function should exist and be callable
        self.assertTrue(callable(build_planner_prompt))

    def test_planning_reads_architecture_md(self) -> None:
        """Planning phase should read from architecture.md."""
        # This is implicit in the planner prompt which includes architecture.md
        import tempfile
        from pathlib import Path

        from agentmux.sessions.state_store import _make_runtime_files
        from agentmux.workflow.prompts import build_planner_prompt

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            feature_dir.mkdir()
            files = _make_runtime_files(project_dir, feature_dir)

            # Create minimal required files
            (feature_dir / "context.md").write_text("# Context")
            (feature_dir / "requirements.md").write_text("# Requirements")
            (feature_dir / "state.json").write_text('{"phase": "planning"}')
            (feature_dir / "02_planning").mkdir(parents=True, exist_ok=True)
            (feature_dir / "02_planning" / "architecture.md").write_text(
                "# Architecture"
            )

            prompt = build_planner_prompt(files)
            # Should reference architecture.md
            self.assertIn("architecture.md", prompt)

    def test_planner_preference_proposal_file_in_prompt(self) -> None:
        """Planner prompt should reference planner_preference_proposal_file."""
        import tempfile
        from pathlib import Path

        from agentmux.sessions.state_store import _make_runtime_files
        from agentmux.workflow.prompts import build_planner_prompt

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            feature_dir.mkdir()
            files = _make_runtime_files(project_dir, feature_dir)

            # Create minimal required files
            (feature_dir / "context.md").write_text("# Context")
            (feature_dir / "requirements.md").write_text("# Requirements")
            (feature_dir / "state.json").write_text('{"phase": "planning"}')
            (feature_dir / "02_planning").mkdir(parents=True, exist_ok=True)
            (feature_dir / "02_planning" / "architecture.md").write_text(
                "# Architecture"
            )

            prompt = build_planner_prompt(files)
            # Should reference planner preference proposal placeholder
            self.assertIn("02_planning/approved_preferences.json", prompt)


class TestInitialPhase(unittest.TestCase):
    """Test that new sessions start in the correct initial phase."""

    def test_create_feature_files_starts_in_architecting_phase(self) -> None:
        """New sessions must start in 'architecting', not 'planning'.

        Regression test for the bug where create_feature_files() set the
        initial phase to 'planning', causing PlanningHandler.enter() to crash
        with FileNotFoundError because architecture.md didn't exist yet.
        """
        import tempfile

        from agentmux.sessions.state_store import create_feature_files, load_state

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            # Simulate what the pipeline does: scaffold a new session
            create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="Fix import shadowing",
                session_name="agentmux-test-session",
                product_manager=False,
            )

            state = load_state(feature_dir / "state.json")
            self.assertEqual(
                state["phase"],
                "architecting",
                "New sessions must start in 'architecting' so the architect can "
                "create architecture.md before the planner runs. Starting in "
                "'planning' causes an immediate FileNotFoundError crash.",
            )

    def test_create_feature_files_with_product_manager_starts_in_product_management(
        self,
    ) -> None:
        """Sessions with product manager still start in 'product_management'."""
        import tempfile

        from agentmux.sessions.state_store import create_feature_files, load_state

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="Fix import shadowing",
                session_name="agentmux-test-session",
                product_manager=True,
            )

            state = load_state(feature_dir / "state.json")
            self.assertEqual(state["phase"], "product_management")

    def test_infer_resume_phase_returns_architecting_when_architecture_missing(
        self,
    ) -> None:
        """infer_resume_phase must return 'architecting' when architecture.md
        is absent.

        A failed session that crashed before the architect wrote architecture.md
        must resume in 'architecting', not 'planning'. Resuming in 'planning'
        would cause the same FileNotFoundError crash.
        """
        import tempfile

        from agentmux.sessions.state_store import infer_resume_phase

        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir()
            # Create 02_planning dir but NO architecture.md
            (feature_dir / "02_planning").mkdir()

            state: dict = {"phase": "failed", "product_manager": False}
            phase = infer_resume_phase(feature_dir, state)
            self.assertEqual(
                phase,
                "architecting",
                "A failed session without architecture.md must resume in "
                "'architecting', not 'planning'.",
            )


class TestDocumentationUpdates(unittest.TestCase):
    """Test that documentation is updated for the new workflow."""

    def setUp(self) -> None:
        self.project_root = Path(__file__).parent.parent

    def test_claude_md_includes_architecting_phase(self) -> None:
        """CLAUDE.md should document the architecting phase in state machine."""
        claude_md = self.project_root / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        # Should mention architecting phase
        self.assertIn("architecting", content)

    def test_claude_md_includes_planner_role(self) -> None:
        """CLAUDE.md should document the planner role."""
        claude_md = self.project_root / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        # Should mention planner role
        self.assertIn("planner", content)

    def test_file_protocol_includes_planner_prompt(self) -> None:
        """docs/file-protocol.md should document planner prompt files."""
        file_protocol = self.project_root / "docs" / "file-protocol.md"
        content = file_protocol.read_text(encoding="utf-8")
        # Should mention planner prompt
        self.assertIn("planner", content.lower())

    def test_prompts_md_includes_planner(self) -> None:
        """docs/prompts.md should document planner prompt template."""
        prompts_md = self.project_root / "docs" / "prompts.md"
        content = prompts_md.read_text(encoding="utf-8")
        # Should mention planner
        self.assertIn("planner", content.lower())

    def test_claude_md_state_machine_diagram_updated(self) -> None:
        """CLAUDE.md state machine diagram should show architecting before planning."""
        claude_md = self.project_root / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        # Should show architecting in the state machine flow
        self.assertIn("architecting", content)

    def test_claude_md_role_routing_includes_planner(self) -> None:
        """CLAUDE.md role routing section should mention planner."""
        claude_md = self.project_root / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        # Should mention planner in role routing
        has_planner = "planner" in content
        self.assertTrue(has_planner, "CLAUDE.md should document planner role")
