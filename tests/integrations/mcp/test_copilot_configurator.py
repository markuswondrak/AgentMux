from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.mcp import CopilotConfigurator, McpServerSpec


class CopilotConfiguratorTests(unittest.TestCase):
    """Tests for CopilotConfigurator class."""

    def _server(self) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux-research",
            module="agentmux.integrations.mcp_research_server",
            env={},
        )

    def setUp(self) -> None:
        self.configurator = CopilotConfigurator()

    def test_provider_is_copilot(self) -> None:
        """provider attribute equals 'copilot'."""
        self.assertEqual(self.configurator.provider, "copilot")

    def test_config_path_returns_home_copilot_mcp_config(self) -> None:
        """config_path(project_dir) → ~/.copilot/mcp-config.json."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                result = self.configurator.config_path(project_dir)
                expected = home_dir / ".copilot" / "mcp-config.json"
                self.assertEqual(result, expected)

    # --- has_server tests ---

    def test_has_server_false_when_config_missing(self) -> None:
        """has_server returns False when config file does not exist."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.assertFalse(
                    self.configurator.has_server(self._server(), project_dir)
                )

    def test_has_server_false_when_config_empty(self) -> None:
        """has_server returns False when config exists but has no mcpServers."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{}", encoding="utf-8")

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.assertFalse(
                    self.configurator.has_server(self._server(), project_dir)
                )

    def test_has_server_false_when_server_not_present(self) -> None:
        """has_server returns False when config exists but server entry is absent."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"mcpServers": {"other-server": {}}}), encoding="utf-8"
            )

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.assertFalse(
                    self.configurator.has_server(self._server(), project_dir)
                )

    def test_has_server_true_when_server_present(self) -> None:
        """has_server returns True when server entry exists in mcpServers."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux-research": {
                                "type": "local",
                                "command": sys.executable,
                                "args": [
                                    "-m",
                                    "agentmux.integrations.mcp_research_server",
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.assertTrue(
                    self.configurator.has_server(self._server(), project_dir)
                )

    # --- install tests ---

    def test_install_creates_config_when_absent(self) -> None:
        """install creates config file and adds server entry when file is absent."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.configurator.install(self._server(), project_dir)

            self.assertTrue(config_path.exists())
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("mcpServers", data)
            server = data["mcpServers"]["agentmux-research"]
            self.assertEqual("local", server["type"])
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(
                ["-m", "agentmux.integrations.mcp_research_server"], server["args"]
            )
            self.assertTrue(server["enabled"])

    def test_install_adds_server_to_existing_config(self) -> None:
        """install preserves existing config and adds server entry."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "playwright": {
                                "type": "local",
                                "command": "npx",
                                "args": ["@playwright/mcp@latest"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.configurator.install(self._server(), project_dir)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("playwright", data["mcpServers"])
            self.assertIn("agentmux-research", data["mcpServers"])

    def test_install_is_idempotent(self) -> None:
        """install called twice does not duplicate the server entry."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.configurator.install(self._server(), project_dir)
                self.configurator.install(self._server(), project_dir)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                1, len([k for k in data["mcpServers"] if k == "agentmux-research"])
            )
            server = data["mcpServers"]["agentmux-research"]
            self.assertEqual("local", server["type"])
            self.assertEqual(sys.executable, server["command"])

    def test_install_refreshes_existing_entry(self) -> None:
        """install overwrites an existing server entry with fresh values."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()
            config_path = home_dir / ".copilot" / "mcp-config.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux-research": {
                                "type": "local",
                                "command": "old-python",
                                "args": ["-m", "old.module"],
                                "enabled": True,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                self.configurator.install(self._server(), project_dir)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            server = data["mcpServers"]["agentmux-research"]
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(
                ["-m", "agentmux.integrations.mcp_research_server"], server["args"]
            )

    # --- prompt_message tests ---

    def test_prompt_message_contains_path_and_provider(self) -> None:
        """prompt_message includes copilot provider label and config path."""
        with tempfile.TemporaryDirectory() as td:
            home_dir = Path(td)
            project_dir = home_dir / "project"
            project_dir.mkdir()

            with patch(
                "agentmux.integrations.mcp.configurators.Path.home",
                return_value=home_dir,
            ):
                msg = self.configurator.prompt_message(
                    self._server(), project_dir, "architect"
                )

            self.assertIn("copilot", msg)
            self.assertIn("architect", msg)
            self.assertIn(str(home_dir / ".copilot" / "mcp-config.json"), msg)


if __name__ == "__main__":
    unittest.main()
