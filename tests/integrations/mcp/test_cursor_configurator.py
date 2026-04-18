from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agentmux.integrations.mcp import CursorConfigurator, McpServerSpec


class CursorConfiguratorTests(unittest.TestCase):
    """Tests for CursorConfigurator class."""

    def _server(self) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux",
            module="agentmux.integrations.mcp_server",
            env={},
        )

    def setUp(self) -> None:
        self.configurator = CursorConfigurator()

    def test_provider_is_cursor(self) -> None:
        """provider attribute equals 'cursor'."""
        self.assertEqual(self.configurator.provider, "cursor")

    def test_config_path_returns_project_cursor_mcp_json(self) -> None:
        """config_path(project_dir) → <project_dir>/.cursor/mcp.json."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            result = self.configurator.config_path(project_dir)
            expected = project_dir / ".cursor" / "mcp.json"
            self.assertEqual(result, expected)

    # --- has_server tests ---

    def test_has_server_false_when_config_missing(self) -> None:
        """has_server returns False when config file does not exist."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            self.assertFalse(self.configurator.has_server(self._server(), project_dir))

    def test_has_server_false_when_config_empty(self) -> None:
        """has_server returns False when config exists but has no mcpServers."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{}", encoding="utf-8")

            self.assertFalse(self.configurator.has_server(self._server(), project_dir))

    def test_has_server_false_when_server_not_present(self) -> None:
        """has_server returns False when config exists but server entry is absent."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps({"mcpServers": {"other-server": {}}}), encoding="utf-8"
            )

            self.assertFalse(self.configurator.has_server(self._server(), project_dir))

    def test_has_server_true_when_server_present(self) -> None:
        """has_server returns True when server entry exists in mcpServers."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux": {
                                "type": "stdio",
                                "command": sys.executable,
                                "args": [
                                    "-m",
                                    "agentmux.integrations.mcp_server",
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(self.configurator.has_server(self._server(), project_dir))

    # --- install tests ---

    def test_install_creates_config_when_absent(self) -> None:
        """install creates config file and adds server entry when file is absent."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"

            self.configurator.install(self._server(), project_dir)

            self.assertTrue(config_path.exists())
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("mcpServers", data)
            server = data["mcpServers"]["agentmux"]
            self.assertEqual("stdio", server["type"])
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(["-m", "agentmux.integrations.mcp_server"], server["args"])

    def test_install_adds_server_to_existing_config(self) -> None:
        """install preserves existing config and adds server entry."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "playwright": {
                                "type": "stdio",
                                "command": "npx",
                                "args": ["@playwright/mcp@latest"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.configurator.install(self._server(), project_dir)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("playwright", data["mcpServers"])
            self.assertIn("agentmux", data["mcpServers"])

    def test_install_is_idempotent(self) -> None:
        """install called twice does not duplicate the server entry."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"

            self.configurator.install(self._server(), project_dir)
            self.configurator.install(self._server(), project_dir)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(1, len([k for k in data["mcpServers"] if k == "agentmux"]))
            server = data["mcpServers"]["agentmux"]
            self.assertEqual("stdio", server["type"])
            self.assertEqual(sys.executable, server["command"])

    def test_install_refreshes_existing_entry(self) -> None:
        """install overwrites an existing server entry with fresh values."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            config_path = project_dir / ".cursor" / "mcp.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "agentmux": {
                                "type": "stdio",
                                "command": "old-python",
                                "args": ["-m", "old.module"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.configurator.install(self._server(), project_dir)

            data = json.loads(config_path.read_text(encoding="utf-8"))
            server = data["mcpServers"]["agentmux"]
            self.assertEqual(sys.executable, server["command"])
            self.assertEqual(["-m", "agentmux.integrations.mcp_server"], server["args"])

    # --- prompt_message tests ---

    def test_prompt_message_contains_path_and_provider(self) -> None:
        """prompt_message includes cursor provider label and config path."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            msg = self.configurator.prompt_message(
                self._server(), project_dir, "architect"
            )

            self.assertIn("cursor", msg)
            self.assertIn("architect", msg)
            self.assertIn(str(project_dir / ".cursor" / "mcp.json"), msg)


if __name__ == "__main__":
    unittest.main()
