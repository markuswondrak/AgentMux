from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.mcp_config import (
    ClaudeInjector,
    CodexInjector,
    GeminiInjector,
    McpServerSpec,
    OpenCodeInjector,
    cleanup_mcp,
    setup_mcp,
)
from agentmux.models import AgentConfig


class McpConfigRequirementsTests(unittest.TestCase):
    def _server(self, feature_dir: Path) -> McpServerSpec:
        return McpServerSpec(
            name="agentmux-research",
            module="agentmux.mcp_research_server",
            env={"FEATURE_DIR": str(feature_dir)},
        )

    def test_claude_injector_writes_config_and_appends_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agent = AgentConfig(role="architect", cli="claude", model="opus", args=["--permission-mode", "acceptEdits"])

            injected = ClaudeInjector().inject(agent, [self._server(feature_dir)], feature_dir, project_dir)

            self.assertIsNotNone(injected)
            assert injected is not None
            self.assertEqual(
                [
                    "--permission-mode",
                    "acceptEdits",
                    "--mcp-config",
                    str(feature_dir / "mcp_claude.json"),
                ],
                injected.args,
            )
            config = json.loads((feature_dir / "mcp_claude.json").read_text(encoding="utf-8"))
            self.assertIn("agentmux-research", config["mcpServers"])
            server = config["mcpServers"]["agentmux-research"]
            self.assertEqual("stdio", server["type"])
            self.assertEqual("python3", server["command"])
            self.assertEqual(["-m", "agentmux.mcp_research_server"], server["args"])
            self.assertEqual({"FEATURE_DIR": str(feature_dir)}, server["env"])

    def test_codex_injector_stages_config_sets_codex_home_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            home_dir = tmp_path / "home"
            (home_dir / ".codex").mkdir(parents=True)
            (home_dir / ".codex" / "config.toml").write_text('foo = "bar"\n', encoding="utf-8")
            feature_dir.mkdir()
            project_dir.mkdir()
            agent = AgentConfig(role="architect", cli="codex", model="gpt-5.3-codex", args=["-a", "never"])

            with patch("agentmux.mcp_config.Path.home", return_value=home_dir):
                injected = CodexInjector().inject(agent, [self._server(feature_dir)], feature_dir, project_dir)
                assert injected is not None
                injected_again = CodexInjector().inject(injected, [self._server(feature_dir)], feature_dir, project_dir)
                assert injected_again is not None

            codex_home = feature_dir / "codex_home"
            config_path = codex_home / "config.toml"
            content = config_path.read_text(encoding="utf-8")
            self.assertIn('foo = "bar"', content)
            self.assertIn("[mcp_servers.agentmux-research]", content)
            self.assertIn('command = "python3"', content)
            self.assertIn('args = ["-m", "agentmux.mcp_research_server"]', content)
            self.assertIn("enabled = true", content)
            self.assertIn("[mcp_servers.agentmux-research.env]", content)
            self.assertIn(f'FEATURE_DIR = "{feature_dir}"', content)
            self.assertEqual(1, content.count("[mcp_servers.agentmux-research]"))
            self.assertEqual(str(codex_home), injected_again.env["CODEX_HOME"])
            self.assertEqual(["-a", "never"], injected_again.args)

    def test_gemini_injector_creates_owned_config_and_cleanup_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agent = AgentConfig(role="architect", cli="gemini", model="gemini-2.5-pro", args=[])

            injected = GeminiInjector().inject(agent, [self._server(feature_dir)], feature_dir, project_dir)

            self.assertEqual(agent, injected)
            settings_path = project_dir / ".gemini" / "settings.json"
            marker_path = feature_dir / "gemini_config_created"
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertTrue(marker_path.exists())
            self.assertTrue(settings["mcpServers"]["agentmux-research"]["trust"])

            GeminiInjector().cleanup(feature_dir, project_dir)
            self.assertFalse(settings_path.exists())
            self.assertFalse(marker_path.exists())
            self.assertFalse((project_dir / ".gemini").exists())

            # idempotent
            GeminiInjector().cleanup(feature_dir, project_dir)

    def test_gemini_injector_skips_when_project_settings_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            (project_dir / ".gemini").mkdir(parents=True)
            (project_dir / ".gemini" / "settings.json").write_text('{"existing": true}\n', encoding="utf-8")
            agent = AgentConfig(role="architect", cli="gemini", model="gemini-2.5-pro", args=[])

            injected = GeminiInjector().inject(agent, [self._server(feature_dir)], feature_dir, project_dir)

            self.assertIsNone(injected)
            self.assertFalse((feature_dir / "gemini_config_created").exists())
            self.assertEqual('{"existing": true}\n', (project_dir / ".gemini" / "settings.json").read_text(encoding="utf-8"))

    def test_opencode_injector_writes_config_and_sets_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agent = AgentConfig(role="architect", cli="opencode", model="anthropic/claude-sonnet-4-20250514", args=[])

            injected = OpenCodeInjector().inject(agent, [self._server(feature_dir)], feature_dir, project_dir)

            self.assertIsNotNone(injected)
            assert injected is not None
            self.assertEqual(str(feature_dir / "mcp_opencode.json"), injected.env["OPENCODE_CONFIG"])
            config = json.loads((feature_dir / "mcp_opencode.json").read_text(encoding="utf-8"))
            server = config["mcp"]["agentmux-research"]
            self.assertEqual("local", server["type"])
            self.assertEqual(["python3", "-m", "agentmux.mcp_research_server"], server["command"])
            self.assertEqual({"FEATURE_DIR": str(feature_dir)}, server["environment"])
            self.assertTrue(server["enabled"])

    def test_setup_mcp_injects_only_selected_roles_and_preserves_other_agents(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            project_dir.mkdir()
            agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
                "product-manager": AgentConfig(role="product-manager", cli="gemini", model="gemini-2.5-pro", args=[]),
                "reviewer": AgentConfig(role="reviewer", cli="claude", model="sonnet", args=[]),
            }

            updated = setup_mcp(
                agents,
                [self._server(feature_dir)],
                ["architect", "product-manager"],
                feature_dir,
                project_dir,
            )

            self.assertIn("--mcp-config", updated["architect"].args)
            self.assertEqual(agents["reviewer"], updated["reviewer"])
            self.assertTrue((feature_dir / "gemini_config_created").exists())
            self.assertTrue((project_dir / ".gemini" / "settings.json").exists())

    def test_cleanup_mcp_removes_only_owned_gemini_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            project_dir = tmp_path / "project"
            feature_dir.mkdir()
            (project_dir / ".gemini").mkdir(parents=True)
            marker = feature_dir / "gemini_config_created"
            settings = project_dir / ".gemini" / "settings.json"
            marker.touch()
            settings.write_text("{}\n", encoding="utf-8")

            cleanup_mcp(feature_dir, project_dir)

            self.assertFalse(marker.exists())
            self.assertFalse(settings.exists())


if __name__ == "__main__":
    unittest.main()
