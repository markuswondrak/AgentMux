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
    McpServerSpec,
    cleanup_mcp,
    ensure_mcp_config,
    setup_mcp,
)
from agentmux.integrations.mcp.runtime import (
    create_runtime_mcp_config as _create_runtime_mcp_config,
)
from agentmux.integrations.opencode_agents import OpenCodeAgentConfigurator
from agentmux.shared.models import OPENCODE_AGENT_ROLES, AgentConfig


class McpConfigRequirementsTests(unittest.TestCase):
    def _server(self) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux",
            module="agentmux.integrations.mcp_server",
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
            server = config["mcpServers"]["agentmux"]
            self.assertTrue(config["existing"])
            self.assertEqual("stdio", server["type"])
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(["-m", "agentmux.integrations.mcp_server"], server["args"])

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
            server = config["mcpServers"]["agentmux"]
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(["-m", "agentmux.integrations.mcp_server"], server["args"])
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
            server = config["mcp"]["agentmux"]
            self.assertEqual({"x": True}, config["tools"])
            self.assertEqual("local", server["type"])
            self.assertEqual(
                [sys.executable, "-m", "agentmux.integrations.mcp_server"],
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
                "[mcp_servers.agentmux]\n"
                'command = "python3"\n'
                'args = ["-m", "agentmux.integrations.mcp_server"]\n'
                "enabled = true\n\n"
                "[mcp_servers.agentmux.env]\n"
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

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
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
            self.assertIn('args = ["-m", "agentmux.integrations.mcp_server"]', content)
            self.assertEqual(1, content.count("[mcp_servers.agentmux]"))
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

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                ensure_mcp_config(
                    agents,
                    [self._server()],
                    ["architect"],
                    project_dir,
                    interactive=False,
                    output=output,
                )

            self.assertIn(
                "Agentmux MCP server not configured for codex", output.getvalue()
            )
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
                    args=["--allowedTools", "mcp__agentmux__*"],
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
            self.assertEqual("mcp_servers_architect.json", Path(config_path_arch).name)
            self.assertIn("--mcp-config", updated["product-manager"].args)
            config_path_pm = updated["product-manager"].args[
                updated["product-manager"].args.index("--mcp-config") + 1
            ]
            self.assertEqual(
                "mcp_servers_product-manager.json", Path(config_path_pm).name
            )

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
            self.assertIn("agentmux", config["mcpServers"])
            server = config["mcpServers"]["agentmux"]
            self.assertEqual("stdio", server["type"])
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(["-m", "agentmux.integrations.mcp_server"], server["args"])
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
                    "agentmux": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": ["-m", "agentmux.integrations.mcp_server"],
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

    def test_runtime_mcp_config_includes_project_env_without_feature_dir(self) -> None:
        """Runtime MCP JSON carries stable project env;
        session paths are not embedded."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()

            config_path = _create_runtime_mcp_config([self._server()], project_dir)

            config = json.loads(config_path.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"]["env"]
            self.assertNotIn("FEATURE_DIR", server_env)
            self.assertIn("PROJECT_DIR", server_env)
            self.assertEqual(str(project_dir), server_env["PROJECT_DIR"])

    def test_runtime_mcp_config_omits_feature_dir_when_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            config_path = _create_runtime_mcp_config([self._server()], project_dir)

            config = json.loads(config_path.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"]["env"]
            self.assertNotIn("FEATURE_DIR", server_env)

    def test_setup_mcp_injects_project_dir_and_allowed_tools_for_non_claude(
        self,
    ) -> None:
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
            }

            env_without_pythonpath = {
                k: v for k, v in os.environ.items() if k != "PYTHONPATH"
            }
            with patch.dict(os.environ, env_without_pythonpath, clear=True):
                updated = setup_mcp(
                    agents,
                    [self._server()],
                    ["architect"],
                    feature_dir,
                    project_dir,
                )

            self.assertNotIn("FEATURE_DIR", updated["architect"].env)
            self.assertNotIn("PROJECT_DIR", updated["architect"].env)
            self.assertIn("PYTHONPATH", updated["architect"].env)
            from agentmux.integrations.mcp.models import ROLE_TOOLS

            allowed = updated["architect"].env["AGENTMUX_ALLOWED_TOOLS"]
            self.assertEqual(
                set(allowed.split(",")),
                set(ROLE_TOOLS["architect"]),
            )

    def test_setup_mcp_injects_mcp_json_for_claude_without_feature_dir(self) -> None:
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
                    args=[],
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["architect"],
                feature_dir,
                project_dir,
            )

            self.assertNotIn("FEATURE_DIR", updated["architect"].env)
            mcp_config_path_str = updated["architect"].args[
                updated["architect"].args.index("--mcp-config") + 1
            ]
            mcp_config = json.loads(Path(mcp_config_path_str).read_text())
            server_env = mcp_config["mcpServers"]["agentmux"]["env"]
            self.assertNotIn("FEATURE_DIR", server_env)
            self.assertEqual(str(project_dir), server_env["PROJECT_DIR"])
            from agentmux.integrations.mcp.models import ROLE_TOOLS

            allowed = server_env["AGENTMUX_ALLOWED_TOOLS"]
            self.assertEqual(
                set(allowed.split(",")),
                set(ROLE_TOOLS["architect"]),
            )

    def test_setup_mcp_injects_env_into_cursor_mcp_json_for_cursor_agent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            # Create .cursor/mcp.json as it would be after `agentmux init`
            cursor_mcp_dir = project_dir / ".cursor"
            cursor_mcp_dir.mkdir()
            cursor_mcp_json = cursor_mcp_dir / "mcp.json"
            cursor_mcp_json.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux": {
                                "type": "stdio",
                                "command": sys.executable,
                                "args": ["-m", "agentmux.integrations.mcp_server"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=["--trust"],
                    provider="cursor",
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["planner"],
                feature_dir,
                project_dir,
            )

            # Agent process env gets PYTHONPATH + AGENTMUX_ALLOWED_TOOLS; PROJECT_DIR
            # is written into .cursor/mcp.json for MCP subprocesses, not the agent env.
            self.assertNotIn("FEATURE_DIR", updated["planner"].env)
            self.assertNotIn("PROJECT_DIR", updated["planner"].env)
            self.assertIn("PYTHONPATH", updated["planner"].env)

            # .cursor/mcp.json must have stable env only — no session-specific keys
            config = json.loads(cursor_mcp_json.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"]["env"]
            self.assertIn("PYTHONPATH", server_env)
            self.assertEqual(str(project_dir), server_env["PROJECT_DIR"])
            self.assertNotIn(
                "FEATURE_DIR",
                server_env,
                (
                    "FEATURE_DIR must not be written into .cursor/mcp.json "
                    "— it changes every session and triggers Cursor's MCP "
                    "approval modal"
                ),
            )
            self.assertNotIn(
                "AGENTMUX_ALLOWED_TOOLS",
                server_env,
                (
                    "AGENTMUX_ALLOWED_TOOLS must not be written into .cursor/mcp.json "
                    "— it must go to .agentmux/.active_session instead"
                ),
            )

            # Session-specific values must appear in .agentmux/.active_session
            active_session_path = project_dir / ".agentmux" / ".active_session"
            self.assertTrue(
                active_session_path.exists(), ".active_session must be created"
            )
            active_data = json.loads(active_session_path.read_text(encoding="utf-8"))
            self.assertEqual(str(feature_dir), active_data["feature_dir"])
            from agentmux.integrations.mcp.models import ROLE_TOOLS

            tools = set(active_data["allowed_tools"].split(","))
            self.assertEqual(tools, set(ROLE_TOOLS["planner"]))

    def test_setup_mcp_skips_cursor_injection_when_no_cursor_mcp_json(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            # .cursor/mcp.json does NOT exist
            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=["--trust"],
                    provider="cursor",
                ),
            }

            # Must not raise even when .cursor/mcp.json is absent
            updated = setup_mcp(
                agents,
                [self._server()],
                ["planner"],
                feature_dir,
                project_dir,
            )

            self.assertNotIn("FEATURE_DIR", updated["planner"].env)
            active_session_path = project_dir / ".agentmux" / ".active_session"
            self.assertTrue(active_session_path.exists())
            active_data = json.loads(active_session_path.read_text(encoding="utf-8"))
            self.assertEqual(str(feature_dir), active_data["feature_dir"])

    def test_setup_mcp_merges_allowed_tools_for_multiple_cursor_roles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            cursor_mcp_dir = project_dir / ".cursor"
            cursor_mcp_dir.mkdir()
            cursor_mcp_json = cursor_mcp_dir / "mcp.json"
            cursor_mcp_json.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux": {
                                "type": "stdio",
                                "command": sys.executable,
                                "args": ["-m", "agentmux.integrations.mcp_server"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=["--trust"],
                    provider="cursor",
                ),
                "coder": AgentConfig(
                    role="coder",
                    cli="agent",
                    model="gemini-3-flash",
                    args=["--trust"],
                    provider="cursor",
                ),
            }

            setup_mcp(
                agents,
                [self._server()],
                ["planner", "coder"],
                feature_dir,
                project_dir,
            )

            # Merged allowed tools must appear in .agentmux/.active_session
            active_session_path = project_dir / ".agentmux" / ".active_session"
            self.assertTrue(
                active_session_path.exists(), ".active_session must be created"
            )
            active_data = json.loads(active_session_path.read_text(encoding="utf-8"))
            tools = set(active_data["allowed_tools"].split(","))
            from agentmux.integrations.mcp.models import ROLE_TOOLS

            expected = set(ROLE_TOOLS["planner"]) | set(ROLE_TOOLS["coder"])
            self.assertEqual(tools, expected)

            # .cursor/mcp.json must NOT have session-specific keys
            config = json.loads(cursor_mcp_json.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"]["env"]
            self.assertNotIn(
                "AGENTMUX_ALLOWED_TOOLS",
                server_env,
                ("AGENTMUX_ALLOWED_TOOLS must not be written into .cursor/mcp.json"),
            )
            self.assertNotIn(
                "FEATURE_DIR",
                server_env,
                ("FEATURE_DIR must not be written into .cursor/mcp.json"),
            )


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

            with patch(
                "agentmux.integrations.opencode_agents.Path.home", return_value=home_dir
            ):
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


class RoleToolFilteringTests(unittest.TestCase):
    """Tests for per-role MCP tool filtering via AGENTMUX_ALLOWED_TOOLS."""

    def _server(self) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux",
            module="agentmux.integrations.mcp_server",
            env={},
        )

    def test_per_role_config_contains_allowed_tools_env(self) -> None:
        """Per-role mcp_servers_<role>.json must carry AGENTMUX_ALLOWED_TOOLS in env."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", args=[]
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["architect"],
                project_dir / "feature",
                project_dir,
            )

            config_path_str = updated["architect"].args[
                updated["architect"].args.index("--mcp-config") + 1
            ]
            config = json.loads(Path(config_path_str).read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"]["env"]
            self.assertIn("AGENTMUX_ALLOWED_TOOLS", server_env)
            allowed = set(server_env["AGENTMUX_ALLOWED_TOOLS"].split(","))
            self.assertIn("submit_architecture", allowed)
            self.assertIn("research_dispatch_code", allowed)
            self.assertIn("research_dispatch_web", allowed)
            # Tools for other roles must NOT appear
            self.assertNotIn("submit_plan", allowed)
            self.assertNotIn("submit_done", allowed)

    def test_different_roles_get_different_config_files(self) -> None:
        """Each Claude role gets its own mcp_servers_<role>.json with distinct tools."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", args=[]
                ),
                "coder": AgentConfig(
                    role="coder", cli="claude", model="sonnet", args=[]
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["architect", "coder"],
                project_dir / "feature",
                project_dir,
            )

            arch_path = updated["architect"].args[
                updated["architect"].args.index("--mcp-config") + 1
            ]
            coder_path = updated["coder"].args[
                updated["coder"].args.index("--mcp-config") + 1
            ]
            self.assertEqual("mcp_servers_architect.json", Path(arch_path).name)
            self.assertEqual("mcp_servers_coder.json", Path(coder_path).name)
            self.assertNotEqual(arch_path, coder_path)

            arch_env = json.loads(Path(arch_path).read_text())["mcpServers"][
                "agentmux"
            ]["env"]["AGENTMUX_ALLOWED_TOOLS"]
            coder_env = json.loads(Path(coder_path).read_text())["mcpServers"][
                "agentmux"
            ]["env"]["AGENTMUX_ALLOWED_TOOLS"]
            self.assertIn("submit_architecture", arch_env)
            self.assertNotIn("submit_architecture", coder_env)
            self.assertIn("submit_done", coder_env)
            self.assertNotIn("submit_done", arch_env)

    def test_non_claude_agents_get_allowed_tools_in_process_env(self) -> None:
        """Non-Claude agents receive AGENTMUX_ALLOWED_TOOLS in their process env."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            agents = {
                "coder": AgentConfig(
                    role="coder", cli="codex", model="gpt-5.3-codex", args=[]
                ),
            }

            updated = setup_mcp(
                agents,
                [self._server()],
                ["coder"],
                project_dir / "feature",
                project_dir,
            )

            self.assertIn("AGENTMUX_ALLOWED_TOOLS", updated["coder"].env)
            self.assertEqual(
                "submit_done", updated["coder"].env["AGENTMUX_ALLOWED_TOOLS"]
            )
            self.assertNotIn("--mcp-config", updated["coder"].args)


class CursorActiveSessionTests(unittest.TestCase):
    """Tests that Cursor MCP setup writes session-specific values to
    .agentmux/.active_session rather than .cursor/mcp.json."""

    def _server(self) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux",
            module="agentmux.integrations.mcp_server",
            env={},
        )

    def _cursor_mcp_json(self) -> dict:
        return {
            "mcpServers": {
                "agentmux": {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "agentmux.integrations.mcp_server"],
                }
            }
        }

    def test_setup_mcp_does_not_write_feature_dir_to_cursor_mcp_json(self) -> None:
        """FEATURE_DIR must never appear in .cursor/mcp.json (avoids approval modal)."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            cursor_mcp_dir = project_dir / ".cursor"
            cursor_mcp_dir.mkdir()
            cursor_mcp_json = cursor_mcp_dir / "mcp.json"
            cursor_mcp_json.write_text(
                json.dumps(self._cursor_mcp_json()), encoding="utf-8"
            )

            agents = {
                "product-manager": AgentConfig(
                    role="product-manager",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            setup_mcp(
                agents,
                [self._server()],
                ["product-manager"],
                feature_dir,
                project_dir,
            )

            config = json.loads(cursor_mcp_json.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"].get("env") or {}
            self.assertNotIn("FEATURE_DIR", server_env)

    def test_setup_mcp_does_not_write_allowed_tools_to_cursor_mcp_json(
        self,
    ) -> None:
        """AGENTMUX_ALLOWED_TOOLS must not appear in .cursor/mcp.json."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            cursor_mcp_dir = project_dir / ".cursor"
            cursor_mcp_dir.mkdir()
            cursor_mcp_json = cursor_mcp_dir / "mcp.json"
            cursor_mcp_json.write_text(
                json.dumps(self._cursor_mcp_json()), encoding="utf-8"
            )

            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            setup_mcp(
                agents,
                [self._server()],
                ["planner"],
                feature_dir,
                project_dir,
            )

            config = json.loads(cursor_mcp_json.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"].get("env") or {}
            self.assertNotIn("AGENTMUX_ALLOWED_TOOLS", server_env)

    def test_setup_mcp_writes_feature_dir_to_active_session(self) -> None:
        """FEATURE_DIR is written to .agentmux/.active_session for Cursor agents."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()

            agents = {
                "product-manager": AgentConfig(
                    role="product-manager",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            setup_mcp(
                agents,
                [self._server()],
                ["product-manager"],
                feature_dir,
                project_dir,
            )

            active_session_path = project_dir / ".agentmux" / ".active_session"
            self.assertTrue(
                active_session_path.exists(),
                ".active_session should be created for Cursor agents",
            )
            data = json.loads(active_session_path.read_text(encoding="utf-8"))
            self.assertEqual(str(feature_dir), data.get("feature_dir"))

    def test_setup_mcp_writes_allowed_tools_to_active_session(self) -> None:
        """AGENTMUX_ALLOWED_TOOLS for the active role is in .active_session."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()

            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            setup_mcp(
                agents,
                [self._server()],
                ["planner"],
                feature_dir,
                project_dir,
            )

            active_session_path = project_dir / ".agentmux" / ".active_session"
            data = json.loads(active_session_path.read_text(encoding="utf-8"))
            self.assertIn("allowed_tools", data)
            from agentmux.integrations.mcp.models import ROLE_TOOLS

            expected = set(ROLE_TOOLS["planner"])
            actual = set(data["allowed_tools"].split(","))
            self.assertEqual(expected, actual)

    def test_setup_mcp_merges_allowed_tools_for_multiple_cursor_roles_in_active_session(
        self,
    ) -> None:
        """Multiple cursor roles have their allowed tools merged in .active_session."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()

            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
                "coder": AgentConfig(
                    role="coder",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            setup_mcp(
                agents,
                [self._server()],
                ["planner", "coder"],
                feature_dir,
                project_dir,
            )

            active_session_path = project_dir / ".agentmux" / ".active_session"
            data = json.loads(active_session_path.read_text(encoding="utf-8"))
            from agentmux.integrations.mcp.models import ROLE_TOOLS

            expected = set(ROLE_TOOLS["planner"]) | set(ROLE_TOOLS["coder"])
            actual = set(data["allowed_tools"].split(","))
            self.assertEqual(expected, actual)

    def test_setup_mcp_writes_active_session_even_without_cursor_mcp_json(
        self,
    ) -> None:
        """.active_session is still written when .cursor/mcp.json is absent."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            # .cursor/mcp.json intentionally absent

            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            updated = setup_mcp(
                agents,
                [self._server()],
                ["planner"],
                feature_dir,
                project_dir,
            )

            active_session_path = project_dir / ".agentmux" / ".active_session"
            self.assertTrue(active_session_path.exists())
            data = json.loads(active_session_path.read_text(encoding="utf-8"))
            self.assertEqual(str(feature_dir), data["feature_dir"])
            self.assertNotIn("FEATURE_DIR", updated["planner"].env)

    def test_setup_mcp_removes_stale_feature_dir_from_cursor_mcp_json(
        self,
    ) -> None:
        """Pre-existing FEATURE_DIR/AGENTMUX_ALLOWED_TOOLS are removed from
        .cursor/mcp.json on first run after the fix (one-time migration)."""
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            cursor_mcp_dir = project_dir / ".cursor"
            cursor_mcp_dir.mkdir()
            cursor_mcp_json = cursor_mcp_dir / "mcp.json"
            cursor_mcp_json.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux": {
                                "type": "stdio",
                                "command": sys.executable,
                                "args": ["-m", "agentmux.integrations.mcp_server"],
                                "env": {
                                    "FEATURE_DIR": "/old/stale/session",
                                    "AGENTMUX_ALLOWED_TOOLS": "submit_plan",
                                    "PROJECT_DIR": str(project_dir),
                                    "PYTHONPATH": str(project_dir),
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            agents = {
                "planner": AgentConfig(
                    role="planner",
                    cli="agent",
                    model="gemini-3-flash",
                    args=[],
                    provider="cursor",
                ),
            }
            setup_mcp(
                agents,
                [self._server()],
                ["planner"],
                feature_dir,
                project_dir,
            )

            config = json.loads(cursor_mcp_json.read_text(encoding="utf-8"))
            server_env = config["mcpServers"]["agentmux"].get("env") or {}
            self.assertNotIn("FEATURE_DIR", server_env)
            self.assertNotIn("AGENTMUX_ALLOWED_TOOLS", server_env)
            # Stable values should still be present
            self.assertIn("PYTHONPATH", server_env)
            self.assertIn("PROJECT_DIR", server_env)


if __name__ == "__main__":
    unittest.main()
