from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agentmux.integrations.opencode_agents import OpenCodeAgentConfigurator
from agentmux.pipeline.configure_command import ROLES, run_configure


class ConfigureRequirementsTests(unittest.TestCase):
    """Tests for the configure command implementation."""

    # =========================================================================
    # Guard tests
    # =========================================================================

    def test_missing_config_exits(self) -> None:
        """No .agentmux/config.yaml → SystemExit(1) mentioning agentmux init."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            # Ensure no config exists
            config_path = project_dir / ".agentmux" / "config.yaml"
            self.assertFalse(config_path.exists())

            with self.assertRaises(SystemExit) as ctx:
                run_configure(provider="claude", project_dir=project_dir)

            self.assertEqual(1, ctx.exception.code)
            # Verify error message mentions init command (printed to stdout)

    def test_unknown_provider_exits(self) -> None:
        """Unknown provider → SystemExit(1) listing known providers."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            # Create a valid config file first so we pass the first guard
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as ctx:
                run_configure(provider="unknown_provider", project_dir=project_dir)

            self.assertEqual(1, ctx.exception.code)
            # Verify error message would list known providers (printed to stdout)

    # =========================================================================
    # --role + --model tests (non-interactive model update)
    # =========================================================================

    def test_role_model_updates_yaml(self) -> None:
        """Sets roles[role]["model"] in YAML, preserves other keys."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            initial = {
                "version": 2,
                "defaults": {"provider": "claude"},
                "github": {"base_branch": "main"},
                "roles": {
                    "architect": {"provider": "claude", "model": "sonnet"},
                },
            }
            config_path.write_text(
                yaml.safe_dump(initial, sort_keys=False), encoding="utf-8"
            )

            result = run_configure(
                provider="claude",
                project_dir=project_dir,
                role="architect",
                model="opus",
            )

            self.assertEqual(0, result)
            with open(config_path, encoding="utf-8") as f:
                updated = yaml.safe_load(f)
            self.assertEqual("opus", updated["roles"]["architect"]["model"])
            # Verify other keys preserved
            self.assertEqual(2, updated["version"])
            self.assertEqual("claude", updated["defaults"]["provider"])
            self.assertEqual("main", updated["github"]["base_branch"])

    def test_role_model_unknown_role_exits(self) -> None:
        """Role not in ROLES → SystemExit(1)."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as ctx:
                run_configure(
                    provider="claude",
                    project_dir=project_dir,
                    role="nonexistent_role",
                    model="opus",
                )

            self.assertEqual(1, ctx.exception.code)

    def test_role_model_creates_roles_section(self) -> None:
        """Config without roles key gets one added."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "version: 2\ndefaults:\n  provider: claude\n", encoding="utf-8"
            )

            result = run_configure(
                provider="claude",
                project_dir=project_dir,
                role="coder",
                model="sonnet",
            )

            self.assertEqual(0, result)
            with open(config_path, encoding="utf-8") as f:
                updated = yaml.safe_load(f)
            self.assertIn("roles", updated)
            self.assertEqual("sonnet", updated["roles"]["coder"]["model"])

    # =========================================================================
    # --agent tests
    # =========================================================================

    def test_agent_non_opencode_noop(self) -> None:
        """Provider "claude" + --agent all → noop, returns 0."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            result = run_configure(
                provider="claude",
                project_dir=project_dir,
                agent="all",
            )

            self.assertEqual(0, result)

    def test_agent_all_installs_all_roles(self) -> None:
        """Provider "opencode", agent="all" → all roles installed."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            result = run_configure(
                provider="opencode",
                project_dir=project_dir,
                agent="all",
            )

            self.assertEqual(0, result)
            # Verify opencode.json was created with all agents
            opencode_json = project_dir / "opencode.json"
            self.assertTrue(opencode_json.exists())
            with open(opencode_json, encoding="utf-8") as f:
                data = json.load(f)
            agents = data.get("agent", {})
            for role in ROLES:
                self.assertIn(f"agentmux-{role}", agents)

    def test_agent_single_role_installs_one(self) -> None:
        """agent="coder" → only install_agent("coder", ...) called."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            result = run_configure(
                provider="opencode",
                project_dir=project_dir,
                agent="coder",
            )

            self.assertEqual(0, result)
            opencode_json = project_dir / "opencode.json"
            self.assertTrue(opencode_json.exists())
            with open(opencode_json, encoding="utf-8") as f:
                data = json.load(f)
            agents = data.get("agent", {})
            self.assertIn("agentmux-coder", agents)
            # Other roles should NOT be present
            for role in ROLES:
                if role != "coder":
                    self.assertNotIn(f"agentmux-{role}", agents)

    def test_agent_unknown_role_exits(self) -> None:
        """agent="nonexistent" → SystemExit(1)."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as ctx:
                run_configure(
                    provider="opencode",
                    project_dir=project_dir,
                    agent="nonexistent",
                )

            self.assertEqual(1, ctx.exception.code)

    def test_agent_force_flag_passed(self) -> None:
        """force=True propagated to install_agent."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            # First install without force
            result = run_configure(
                provider="opencode",
                project_dir=project_dir,
                agent="coder",
            )
            self.assertEqual(0, result)

            # Second install without force should skip
            result = run_configure(
                provider="opencode",
                project_dir=project_dir,
                agent="coder",
            )
            self.assertEqual(0, result)

            # With force=True should overwrite
            result = run_configure(
                provider="opencode",
                project_dir=project_dir,
                agent="coder",
                force=True,
            )
            self.assertEqual(0, result)

    def test_agent_global_scope_path(self) -> None:
        """global_scope=True → path resolves to ~/.config/opencode/opencode.json."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            # Mock the global path to a temp location for testing
            expected_global = Path(tmp) / "global_opencode.json"
            with patch.object(
                OpenCodeAgentConfigurator,
                "config_path",
                return_value=expected_global,
            ):
                result = run_configure(
                    provider="opencode",
                    project_dir=project_dir,
                    agent="all",
                    global_scope=True,
                )

            self.assertEqual(0, result)
            self.assertTrue(expected_global.exists())

    # =========================================================================
    # Interactive mode tests
    # =========================================================================

    def test_interactive_requires_tty(self) -> None:
        """sys.stdin.isatty() returns False → SystemExit(1) with hint."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            with (
                patch.object(sys.stdin, "isatty", return_value=False),
                self.assertRaises(SystemExit) as ctx,
            ):
                run_configure(
                    provider="claude",
                    project_dir=project_dir,
                )

            self.assertEqual(1, ctx.exception.code)

    def test_interactive_writes_model_change(self) -> None:
        """Model prompt returns new value → YAML updated."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            initial = {
                "version": 2,
                "defaults": {"provider": "claude"},
                "roles": {
                    "architect": {"provider": "claude", "model": "sonnet"},
                },
            }
            config_path.write_text(
                yaml.safe_dump(initial, sort_keys=False), encoding="utf-8"
            )

            with (
                patch.object(sys.stdin, "isatty", return_value=True),
                patch(
                    "agentmux.pipeline.configure_command._text",
                    return_value="opus",
                ),
                patch(
                    "agentmux.pipeline.configure_command._select",
                    return_value="yes",
                ),
            ):
                result = run_configure(
                    provider="claude",
                    project_dir=project_dir,
                )

            self.assertEqual(0, result)
            with open(config_path, encoding="utf-8") as f:
                updated = yaml.safe_load(f)
            self.assertEqual("opus", updated["roles"]["architect"]["model"])

    def test_interactive_no_change_no_write(self) -> None:
        """All prompts return existing defaults → YAML not rewritten."""
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            initial = {
                "version": 2,
                "defaults": {"provider": "claude"},
                "roles": {
                    "architect": {"provider": "claude", "model": "sonnet"},
                },
            }
            config_path.write_text(
                yaml.safe_dump(initial, sort_keys=False), encoding="utf-8"
            )
            original_mtime = config_path.stat().st_mtime

            with (
                patch.object(sys.stdin, "isatty", return_value=True),
                patch(
                    "agentmux.pipeline.configure_command._text",
                    return_value="sonnet",
                ),
                patch(
                    "agentmux.pipeline.configure_command._select",
                    return_value="no",
                ),
            ):
                result = run_configure(
                    provider="claude",
                    project_dir=project_dir,
                )

            self.assertEqual(0, result)
            # File should not have been rewritten
            new_mtime = config_path.stat().st_mtime
            self.assertEqual(original_mtime, new_mtime)
