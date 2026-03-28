from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agentmux.configuration import load_explicit_config, load_layered_config
from agentmux.configuration.providers import PROVIDERS, get_provider, resolve_agent
from agentmux.shared.models import AgentConfig
from agentmux.runtime.tmux_control import build_agent_command
from agentmux.runtime.tmux_control import accept_trust_prompt


class ProviderAbstractionTests(unittest.TestCase):
    def test_get_provider_rejects_unknown_name(self) -> None:
        with self.assertRaises(ValueError):
            get_provider("unknown-provider")

    def test_resolve_agent_uses_role_provider_tier_and_args_override(self) -> None:
        agent = resolve_agent(
            global_provider=get_provider("claude"),
            role="coder",
            role_config={"provider": "codex", "profile": "low", "args": ["--x"]},
        )
        self.assertEqual("coder", agent.role)
        self.assertEqual(PROVIDERS["codex"].cli, agent.cli)
        self.assertEqual("gpt-5.1-codex-mini", agent.model)
        self.assertEqual(["--x"], agent.args)
        self.assertIsNone(agent.trust_snippet)

    def test_load_config_resolves_global_provider_defaults_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = {
                "defaults": {"session_name": "s", "provider": "claude"},
                "roles": {
                    "architect": {"profile": "max"},
                    "reviewer": {"profile": "standard"},
                    "coder": {"provider": "codex", "profile": "standard"},
                },
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)
            session_name = loaded.session_name
            agents = loaded.agents
            max_review_iterations = loaded.max_review_iterations

            self.assertEqual("s", session_name)
            self.assertEqual(3, max_review_iterations)
            self.assertEqual("claude", agents["architect"].cli)
            self.assertEqual("opus", agents["architect"].model)
            self.assertEqual("claude", agents["reviewer"].cli)
            self.assertEqual("sonnet", agents["reviewer"].model)
            self.assertEqual("codex", agents["coder"].cli)
            self.assertEqual("gpt-5.3-codex", agents["coder"].model)
            self.assertNotIn("docs", agents)

    def test_load_layered_config_supports_yaml_profiles_and_custom_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            user_cfg_dir = Path(td) / "user"
            user_cfg_dir.mkdir()
            user_cfg_path = user_cfg_dir / "config.yaml"
            user_cfg_path.write_text(
                """
launchers:
  kimi:
    command: kimi
    model_flag: --model-name
    trust_snippet: Trust custom launcher?
    role_args:
      coder: [--sandbox, workspace-write]
profiles:
  kimi:
    low:
      model: kimi-2.5
roles:
  coder:
    provider: kimi
    profile: low
""".strip()
                + "\n",
                encoding="utf-8",
            )
            project_cfg_dir = project_dir / ".agentmux"
            project_cfg_dir.mkdir()
            (project_cfg_dir / "config.yaml").write_text(
                """
roles:
  coder:
    provider: kimi
    profile: low
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", user_cfg_path):
                loaded = load_layered_config(project_dir)

            coder = loaded.agents["coder"]
            self.assertEqual("kimi", coder.cli)
            self.assertEqual("--model-name", coder.model_flag)
            self.assertEqual("kimi-2.5", coder.model)
            self.assertEqual(["--sandbox", "workspace-write"], coder.args)
            self.assertEqual("Trust custom launcher?", coder.trust_snippet)

    def test_load_layered_config_defaults_skip_final_approval_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                loaded = load_layered_config(project_dir)

            self.assertFalse(loaded.workflow_settings.completion.skip_final_approval)

    def test_load_layered_config_exposes_completion_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                loaded = load_layered_config(project_dir)

            self.assertFalse(loaded.workflow_settings.completion.skip_final_approval)
            self.assertTrue(loaded.workflow_settings.completion.require_final_approval)

    def test_project_config_can_enable_skip_final_approval(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
defaults:
  completion:
    skip_final_approval: true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                loaded = load_layered_config(project_dir)

            self.assertTrue(loaded.workflow_settings.completion.skip_final_approval)

    def test_project_config_can_set_completion_settings_nested_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
defaults:
  completion:
    skip_final_approval: true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                loaded = load_layered_config(project_dir)

            self.assertTrue(loaded.workflow_settings.completion.skip_final_approval)
            self.assertFalse(loaded.workflow_settings.completion.require_final_approval)

    def test_project_config_rejects_require_final_approval_alias(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
defaults:
  completion:
    require_final_approval: false
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                with self.assertRaises(ValueError) as exc:
                    load_layered_config(project_dir)

            self.assertIn("no longer supported", str(exc.exception))

    def test_invalid_completion_settings_conflicting_booleans_fail_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
defaults:
  completion:
    skip_final_approval: true
    require_final_approval: true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                with self.assertRaises(ValueError) as exc:
                    load_layered_config(project_dir)

            self.assertIn("no longer supported", str(exc.exception))

    def test_invalid_skip_final_approval_value_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
defaults:
  skip_final_approval: maybe
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                with self.assertRaises(ValueError) as exc:
                    load_layered_config(project_dir)

            self.assertIn("Legacy defaults keys are no longer supported", str(exc.exception))

    def test_built_in_defaults_include_skip_final_approval_false(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load(
            (repo_root / "agentmux" / "configuration" / "defaults" / "config.yaml").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("completion", config["defaults"])
        self.assertFalse(config["defaults"]["completion"]["skip_final_approval"])

    def test_project_config_cannot_define_launchers_or_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg_dir = project_dir / ".agentmux"
            project_cfg_dir.mkdir()
            (project_cfg_dir / "config.yaml").write_text(
                """
launchers:
  kimi:
    command: kimi
profiles:
  kimi:
    low:
      model: kimi-2.5
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                with self.assertRaises(ValueError):
                    load_layered_config(project_dir)

    def test_accept_trust_prompt_skips_when_no_snippet(self) -> None:
        with patch("agentmux.runtime.tmux_control.capture_pane") as capture_pane, patch("agentmux.runtime.tmux_control.run_command") as run_command:
            accept_trust_prompt("%1", snippet=None)
        capture_pane.assert_not_called()
        run_command.assert_not_called()

    def test_build_agent_command_uses_launcher_specific_model_flag(self) -> None:
        command = build_agent_command(
            AgentConfig(
                role="coder",
                cli="kimi",
                model="kimi-2.5",
                model_flag="--model-name",
                args=["--sandbox", "workspace-write"],
            )
        )
        self.assertEqual("kimi --model-name kimi-2.5 --sandbox workspace-write", command)

    def test_accept_trust_prompt_accepts_when_snippet_is_present(self) -> None:
        commands: list[list[str]] = []

        with patch(
            "agentmux.runtime.tmux_control.capture_pane",
            side_effect=["some output", "Trust this folder?"],
        ), patch(
            "agentmux.runtime.tmux_control.run_command",
            side_effect=lambda args, cwd=None, check=True: commands.append(args),
        ):
            accept_trust_prompt("%1", snippet="Trust this folder?", timeout_seconds=0.5)

        self.assertEqual(
            [
                ["tmux", "select-pane", "-t", "%1"],
                ["tmux", "send-keys", "-t", "%1", "Enter"],
            ],
            commands,
        )


if __name__ == "__main__":
    unittest.main()
