from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.mcp import (
    OPENCODE_AGENT_ROLES,
    McpServerSpec,
    OpenCodeAgentConfigurator,
    _create_runtime_mcp_config,
    cleanup_mcp,
    ensure_mcp_config,
    setup_mcp,
)
from agentmux.shared.models import AgentConfig


class McpConfigRequirementsTests(unittest.TestCase):
    def _server(self) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux-research",
            module="agentmux.integrations.mcp_research_server",
            env={},
        )

    def test_setup_mcp_adds_pythonpath_for_selected_roles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="codex",
                    model="gpt-5.3-codex",
                    args=["-a", "never"],
                ),
                "product-manager": AgentConfig(
                    role="product-manager", cli="claude", model="opus", args=[]
                ),
                "reviewer": AgentConfig(
                    role="reviewer", cli="claude", model="sonnet", args=[]
                ),
            }

            env_without_pythonpath = {
                k: v for k, v in os.environ.items() if k != "PYTHONPATH"
            }
            with patch.dict(os.environ, env_without_pythonpath, clear=True):
                updated = setup_mcp(
                    agents,
                    [self._server()],
                    ["architect", "product-manager"],
                    feature_dir,
                    project_dir,
                )

            self.assertEqual(str(project_dir), updated["architect"].env["PYTHONPATH"])
            self.assertEqual(
                str(project_dir), updated["product-manager"].env["PYTHONPATH"]
            )
            self.assertIsNone(updated["reviewer"].env)

    def test_setup_mcp_prepends_existing_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agent = AgentConfig(
                role="architect",
                cli="claude",
                model="opus",
                env={"PYTHONPATH": "/existing/path"},
            )

            updated = setup_mcp(
                {"architect": agent},
                [self._server()],
                ["architect"],
                feature_dir,
                project_dir,
            )

            self.assertEqual(
                os.pathsep.join([str(project_dir), "/existing/path"]),
                updated["architect"].env["PYTHONPATH"],
            )

    def test_ensure_mcp_config_writes_claude_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".claude" / "settings.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text('{"existing": true}\n', encoding="utf-8")
            agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", provider="claude"
                ),
            }

            ensure_mcp_config(
                agents,
                [self._server()],
                ["architect"],
                project_dir,
                interactive=True,
                confirm=lambda _message: True,
            )

            config = json.loads(config_path.read_text(encoding="utf-8"))
            server = config["mcpServers"]["agentmux-research"]
            self.assertTrue(config["existing"])
            self.assertEqual("stdio", server["type"])
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(
                ["-m", "agentmux.integrations.mcp_research_server"], server["args"]
            )

    def test_ensure_mcp_config_writes_gemini_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            agents = {
                "product-manager": AgentConfig(
                    role="product-manager",
                    cli="gemini",
                    model="gemini-2.5-pro",
                    provider="gemini",
                ),
            }

            ensure_mcp_config(
                agents,
                [self._server()],
                ["product-manager"],
                project_dir,
                interactive=True,
                confirm=lambda _message: True,
            )

            config = json.loads(
                (project_dir / ".gemini" / "settings.json").read_text(encoding="utf-8")
            )
            server = config["mcpServers"]["agentmux-research"]
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(
                ["-m", "agentmux.integrations.mcp_research_server"], server["args"]
            )
            self.assertTrue(server["trust"])

    def test_ensure_mcp_config_writes_opencode_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / "opencode.json"
            config_path.write_text('{"tools": {"x": true}}\n', encoding="utf-8")
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="opencode",
                    model="sonnet",
                    provider="opencode",
                ),
            }

            ensure_mcp_config(
                agents,
                [self._server()],
                ["architect"],
                project_dir,
                interactive=True,
                confirm=lambda _message: True,
            )

            config = json.loads(config_path.read_text(encoding="utf-8"))
            server = config["mcp"]["agentmux-research"]
            self.assertEqual({"x": True}, config["tools"])
            self.assertEqual("local", server["type"])
            self.assertEqual(
                [sys.executable, "-m", "agentmux.integrations.mcp_research_server"],
                server["command"],
            )
            self.assertTrue(server["enabled"])

    def test_ensure_mcp_config_writes_codex_user_config_and_refreshes_existing_block(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".codex" / "config.toml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                'foo = "bar"\n\n'
                "[mcp_servers.agentmux-research]\n"
                'command = "python3"\n'
                'args = ["-m", "agentmux.integrations.mcp_research_server"]\n'
                "enabled = true\n\n"
                "[mcp_servers.agentmux-research.env]\n"
                'FEATURE_DIR = "/old/feature"\n',
                encoding="utf-8",
            )
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="codex",
                    model="gpt-5.3-codex",
                    provider="codex",
                ),
            }

            with patch("agentmux.integrations.mcp.Path.home", return_value=home_dir):
                ensure_mcp_config(
                    agents,
                    [self._server()],
                    ["architect"],
                    project_dir,
                    interactive=True,
                    confirm=lambda _message: True,
                )

            content = config_path.read_text(encoding="utf-8")
            self.assertIn('foo = "bar"', content)
            self.assertIn(f'command = "{sys.executable}"', content)
            self.assertIn(
                'args = ["-m", "agentmux.integrations.mcp_research_server"]', content
            )
            self.assertEqual(1, content.count("[mcp_servers.agentmux-research]"))
            self.assertNotIn('FEATURE_DIR = "/old/feature"', content)

    def test_ensure_mcp_config_warns_when_noninteractive_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="codex",
                    model="gpt-5.3-codex",
                    provider="codex",
                ),
            }
            output = io.StringIO()

            with patch("agentmux.integrations.mcp.Path.home", return_value=home_dir):
                ensure_mcp_config(
                    agents,
                    [self._server()],
                    ["architect"],
                    project_dir,
                    interactive=False,
                    output=output,
                )

            self.assertIn("Missing MCP config for codex", output.getvalue())
            self.assertFalse((home_dir / ".codex" / "config.toml").exists())

    def test_ensure_mcp_config_dedupes_shared_provider_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", provider="claude"
                ),
                "product-manager": AgentConfig(
                    role="product-manager",
                    cli="claude",
                    model="opus",
                    provider="claude",
                ),
            }
            prompts: list[str] = []

            ensure_mcp_config(
                agents,
                [self._server()],
                ["architect", "product-manager"],
                project_dir,
                interactive=True,
                confirm=lambda message: prompts.append(message) or True,
            )

            self.assertEqual(1, len(prompts))
            self.assertIn("architect, product-manager", prompts[0])
            self.assertIn(str(project_dir / ".claude" / "settings.json"), prompts[0])

    def test_cleanup_mcp_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()

            cleanup_mcp(feature_dir, project_dir)

            self.assertTrue(feature_dir.exists())
            self.assertTrue(project_dir.exists())

    def test_setup_mcp_adds_mcp_config_flag_for_claude_agents(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="claude",
                    model="opus",
                    args=["--allowedTools", "mcp__agentmux-research__*"],
                ),
                "product-manager": AgentConfig(
                    role="product-manager", cli="claude", model="sonnet", args=[]
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["architect", "product-manager"],
                feature_dir,
                project_dir,
            )

            # Check that --mcp-config flag and path are added to Claude agents
            self.assertIn("--mcp-config", updated["architect"].args)
            config_path_arch = updated["architect"].args[
                updated["architect"].args.index("--mcp-config") + 1
            ]
            self.assertTrue(Path(config_path_arch).name == "mcp_servers.json")
            self.assertIn("--mcp-config", updated["product-manager"].args)
            config_path_pm = updated["product-manager"].args[
                updated["product-manager"].args.index("--mcp-config") + 1
            ]
            self.assertTrue(Path(config_path_pm).name == "mcp_servers.json")

    def test_setup_mcp_skips_mcp_config_for_non_claude_agents(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="codex",
                    model="gpt-5.3-codex",
                    args=["-a", "never"],
                ),
                "coder": AgentConfig(
                    role="coder", cli="gemini", model="gemini-2.5-pro", args=[]
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["architect", "coder"],
                feature_dir,
                project_dir,
            )

            # Verify non-Claude agents don't get --mcp-config
            self.assertNotIn("--mcp-config", updated["architect"].args)
            self.assertNotIn("--mcp-config", updated["coder"].args)

    def test_runtime_mcp_config_file_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            agentmux_dir = project_dir / ".agentmux"
            feature_dir.mkdir()
            project_dir.mkdir()

            config_path = _create_runtime_mcp_config([self._server()], project_dir)

            # Verify file exists with correct structure
            self.assertTrue(config_path.exists())
            self.assertEqual(config_path.parent, agentmux_dir)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("mcpServers", config)
            self.assertIn("agentmux-research", config["mcpServers"])
            server = config["mcpServers"]["agentmux-research"]
            self.assertEqual("stdio", server["type"])
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(
                ["-m", "agentmux.integrations.mcp_research_server"], server["args"]
            )
            self.assertIn("env", server)
            self.assertEqual(str(project_dir), server["env"]["PYTHONPATH"])

    def test_runtime_mcp_config_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            # tempfile already created the directory

            # Create the file first
            config_path = _create_runtime_mcp_config([self._server()], project_dir)
            original_mtime = config_path.stat().st_mtime

            # Call again with same content
            config_path2 = _create_runtime_mcp_config([self._server()], project_dir)
            new_mtime = config_path2.stat().st_mtime

            # Verify file wasn't modified (mtime unchanged)
            self.assertEqual(original_mtime, new_mtime)
            self.assertEqual(config_path, config_path2)

    def test_ensure_mcp_config_skips_install_when_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".claude" / "settings.json"
            config_path.parent.mkdir(parents=True)
            # Create existing config that matches what would be generated
            existing_config = {
                "mcpServers": {
                    "agentmux-research": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": ["-m", "agentmux.integrations.mcp_research_server"],
                    }
                }
            }
            config_path.write_text(json.dumps(existing_config), encoding="utf-8")

            agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", provider="claude"
                ),
            }

            # Mock the install method to track if it's called
            with patch(
                "agentmux.integrations.mcp.ClaudeConfigurator.install"
            ) as mock_install:
                ensure_mcp_config(
                    agents,
                    [self._server()],
                    ["architect"],
                    project_dir,
                    interactive=True,
                    confirm=lambda _message: True,
                )
                # install() should not be called when config is unchanged
                mock_install.assert_not_called()


class OpenCodeAgentConfiguratorTests(unittest.TestCase):
    """Tests for OpenCodeAgentConfigurator class."""

    def setUp(self) -> None:
        self.configurator = OpenCodeAgentConfigurator()

    def test_config_path_project_scope(self) -> None:
        """config_path(project_dir) → project_dir/opencode.json"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            result = self.configurator.config_path(project_dir)
            self.assertEqual(result, project_dir / "opencode.json")

    def test_config_path_global_scope(self) -> None:
        """config_path(global_scope=True) → ~/.config/opencode/opencode.json"""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()

            with patch("agentmux.integrations.mcp.Path.home", return_value=home_dir):
                result = self.configurator.config_path(project_dir, global_scope=True)
                expected = home_dir / ".config" / "opencode" / "opencode.json"
                self.assertEqual(result, expected)

    def test_install_agent_creates_entry(self) -> None:
        """Fresh file → install_agent returns 'created', entry present in JSON"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / "opencode.json"

            result = self.configurator.install_agent("coder", config_path)

            self.assertEqual(result, "created")
            self.assertTrue(config_path.exists())

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("agent", data)
            self.assertIn("agentmux-coder", data["agent"])
            entry = data["agent"]["agentmux-coder"]
            self.assertEqual(entry["mode"], "primary")
            self.assertIn("description", entry)
            self.assertIn("prompt", entry)

    def test_install_agent_skips_existing(self) -> None:
        """Pre-existing entry, force=False → returns 'skipped', entry unchanged"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / "opencode.json"

            # First install
            self.configurator.install_agent("coder", config_path)
            original_data = json.loads(config_path.read_text(encoding="utf-8"))

            # Second install without force should skip
            result = self.configurator.install_agent("coder", config_path, force=False)

            self.assertEqual(result, "skipped")
            new_data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(original_data, new_data)

    def test_install_agent_force_overwrites(self) -> None:
        """Pre-existing entry, force=True → returns 'overwritten'"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / "opencode.json"

            # First install
            self.configurator.install_agent("coder", config_path)

            # Second install with force should overwrite
            result = self.configurator.install_agent("coder", config_path, force=True)

            self.assertEqual(result, "overwritten")

    def test_install_all_agents(self) -> None:
        """install_all_agents returns dict with all 8 roles as keys"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / "opencode.json"

            result = self.configurator.install_all_agents(config_path)

            # Check all 8 roles are in the result
            self.assertEqual(len(result), 8)
            for role in OPENCODE_AGENT_ROLES:
                self.assertIn(role, result)
                self.assertIn(result[role], ["created", "skipped", "overwritten"])

    def test_preserves_other_keys(self) -> None:
        """Other keys in opencode.json ($schema, mcp) survive an install_agent call."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / "opencode.json"

            # Pre-populate with other keys
            initial_data = {
                "$schema": "https://example.com/schema.json",
                "mcp": {"some-server": {"enabled": True}},
                "tools": {"x": True},
            }
            config_path.write_text(json.dumps(initial_data), encoding="utf-8")

            # Install an agent
            self.configurator.install_agent("coder", config_path)

            # Verify other keys are preserved
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(data["$schema"], "https://example.com/schema.json")
            self.assertEqual(data["mcp"], {"some-server": {"enabled": True}})
            self.assertEqual(data["tools"], {"x": True})
            self.assertIn("agent", data)

    def test_creates_parent_dirs(self) -> None:
        """Target path in a non-existent subdir → parent dirs created"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            nested_config_path = project_dir / "nested" / "deep" / "opencode.json"

            result = self.configurator.install_agent("coder", nested_config_path)

            self.assertEqual(result, "created")
            self.assertTrue(nested_config_path.exists())

            data = json.loads(nested_config_path.read_text(encoding="utf-8"))
            self.assertIn("agent", data)
            self.assertIn("agentmux-coder", data["agent"])


if __name__ == "__main__":
    unittest.main()
