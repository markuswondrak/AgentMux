"""Test for initial phase state initialization bug fix.

This test verifies that when product_manager=False, the initial phase
is set to "architecting" (not "planning") to ensure architecture.md
is created before the planning phase attempts to use it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files


class TestInitialPhaseState(unittest.TestCase):
    """Test that initial phase is correctly set based on product_manager flag."""

    def test_initial_phase_is_architecting_when_no_product_manager(self) -> None:
        """When product_manager=False, phase should be 'architecting'.

        This is critical because:
        1. The architect creates architecture.md during architecting phase
        2. The planner prompt requires [[include:02_planning/architecture.md]]
        3. If we start at 'planning', the prompt build fails with FileNotFoundError
        """
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="Test feature request",
                session_name="test-session",
                product_manager=False,  # No product manager phase
            )

            # Read the created state file
            import json

            state = json.loads(files.state.read_text(encoding="utf-8"))

            # CRITICAL: Phase must be 'architecting' NOT 'planning'
            # Starting at 'planning' causes FileNotFoundError for architecture.md
            self.assertEqual(
                state["phase"],
                "architecting",
                "When product_manager=False, initial phase must be 'architecting' "
                "to ensure architecture.md is created before planning phase. "
                "Starting at 'planning' causes FileNotFoundError.",
            )

    def test_initial_phase_is_product_management_when_flag_set(self) -> None:
        """When product_manager=True, phase should be 'product_management'."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="Test feature request",
                session_name="test-session",
                product_manager=True,  # With product manager phase
            )

            import json

            state = json.loads(files.state.read_text(encoding="utf-8"))

            self.assertEqual(
                state["phase"],
                "product_management",
                "When product_manager=True, initial phase must be "
                "'product_management'.",
            )

    def test_product_manager_flag_persisted_in_state(self) -> None:
        """The product_manager flag should be persisted in state."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="Test feature request",
                session_name="test-session",
                product_manager=False,
            )

            import json

            state = json.loads(files.state.read_text(encoding="utf-8"))

            self.assertIn("product_manager", state)
            self.assertFalse(state["product_manager"])

    def test_initial_state_has_implementation_single_coder_false(self) -> None:
        """Initial state should include implementation_single_coder=False."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="Test feature request",
                session_name="test-session",
                product_manager=False,
            )

            import json

            state = json.loads(files.state.read_text(encoding="utf-8"))

            self.assertIn("implementation_single_coder", state)
            self.assertFalse(state["implementation_single_coder"])


if __name__ == "__main__":
    unittest.main()
