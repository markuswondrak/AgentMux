from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agentmux.configuration import load_explicit_config, load_layered_config
from agentmux.configuration.providers import PROVIDERS, get_provider, resolve_agent
from agentmux.runtime.command_builder import build_agent_command
from agentmux.runtime.pane_io import accept_trust_prompt
from agentmux.shared.models import AgentConfig, BatchCommand, BatchCommandMode


class ProviderAbstractionTests(unittest.TestCase):
    def test_get_provider_rejects_unknown_name(self) -> None:
        with self.assertRaises(ValueError):
            get_provider("unknown-provider")

    def test_resolve_agent_uses_role_provider_model_and_args_override(self) -> None:
        agent = resolve_agent(
            global_provider=get_provider("claude"),
            role="coder",
            role_config={
                "provider": "codex",
                "model": "gpt-5.1-codex-mini",
                "args": ["--x"],
            },
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
                "version": 2,
                "defaults": {
                    "session_name": "s",
                    "provider": "claude",
                    "model": "sonnet",
                },
                "roles": {
                    "architect": {"model": "opus"},
                    "reviewer": {"model": "sonnet"},
                    "coder": {"provider": "codex", "model": "gpt-5.3-codex"},
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

    def test_load_layered_config_supports_yaml_and_custom_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            user_cfg_dir = Path(td) / "user"
            user_cfg_dir.mkdir()
            user_cfg_path = user_cfg_dir / "config.yaml"
            user_cfg_path.write_text(
                """
version: 2
providers:
  kimi:
    command: kimi
    model_flag: --model-name
    trust_snippet: Trust custom provider?
    role_args:
      coder: [--sandbox, workspace-write]
roles:
  coder:
    provider: kimi
    model: kimi-2.5
""".strip()
                + "\n",
                encoding="utf-8",
            )
            project_cfg_dir = project_dir / ".agentmux"
            project_cfg_dir.mkdir()
            (project_cfg_dir / "config.yaml").write_text(
                """
version: 2
roles:
  coder:
    provider: kimi
    model: kimi-2.5
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
            self.assertEqual("Trust custom provider?", coder.trust_snippet)

    def test_load_layered_config_defaults_skip_final_approval_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            with patch(
                "agentmux.configuration.USER_CONFIG_PATH",
                Path(td) / "missing-user-config.yaml",
            ):
                loaded = load_layered_config(project_dir)

            self.assertFalse(loaded.workflow_settings.completion.skip_final_approval)

    def test_load_layered_config_exposes_completion_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            with patch(
                "agentmux.configuration.USER_CONFIG_PATH",
                Path(td) / "missing-user-config.yaml",
            ):
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
version: 2
defaults:
  completion:
    skip_final_approval: true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "agentmux.configuration.USER_CONFIG_PATH",
                Path(td) / "missing-user-config.yaml",
            ):
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
version: 2
defaults:
  completion:
    skip_final_approval: true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "agentmux.configuration.USER_CONFIG_PATH",
                Path(td) / "missing-user-config.yaml",
            ):
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
version: 2
defaults:
  completion:
    require_final_approval: false
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with (
                patch(
                    "agentmux.configuration.USER_CONFIG_PATH",
                    Path(td) / "missing-user-config.yaml",
                ),
                self.assertRaises(ValueError) as exc,
            ):
                load_layered_config(project_dir)

            self.assertIn("no longer supported", str(exc.exception))

    def test_invalid_completion_settings_conflicting_booleans_fail_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
version: 2
defaults:
  completion:
    skip_final_approval: true
    require_final_approval: true
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with (
                patch(
                    "agentmux.configuration.USER_CONFIG_PATH",
                    Path(td) / "missing-user-config.yaml",
                ),
                self.assertRaises(ValueError) as exc,
            ):
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
version: 2
defaults:
  skip_final_approval: maybe
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with (
                patch(
                    "agentmux.configuration.USER_CONFIG_PATH",
                    Path(td) / "missing-user-config.yaml",
                ),
                self.assertRaises(ValueError) as exc,
            ):
                load_layered_config(project_dir)

            self.assertIn(
                "Legacy defaults keys are no longer supported", str(exc.exception)
            )

    def test_built_in_defaults_include_skip_final_approval_false(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load(
            (
                repo_root
                / "src"
                / "agentmux"
                / "configuration"
                / "defaults"
                / "config.yaml"
            ).read_text(encoding="utf-8")
        )

        self.assertIn("completion", config["defaults"])
        self.assertFalse(config["defaults"]["completion"]["skip_final_approval"])

    def test_project_config_can_define_providers(self) -> None:
        """In v2, project configs CAN define custom providers."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg_dir = project_dir / ".agentmux"
            project_cfg_dir.mkdir()
            (project_cfg_dir / "config.yaml").write_text(
                """
version: 2
providers:
  kimi:
    command: kimi
    model_flag: --model-name
roles:
  coder:
    provider: kimi
    model: kimi-2.5
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "agentmux.configuration.USER_CONFIG_PATH",
                Path(td) / "missing-user-config.yaml",
            ):
                loaded = load_layered_config(project_dir)

            # In v2, project configs CAN define providers
            coder = loaded.agents["coder"]
            self.assertEqual("kimi", coder.cli)
            self.assertEqual("kimi-2.5", coder.model)

    def test_accept_trust_prompt_skips_when_no_snippet(self) -> None:
        with (
            patch("agentmux.runtime.pane_io.capture_pane") as capture_pane,
            patch("agentmux.runtime.pane_io.run_command") as run_command,
        ):
            accept_trust_prompt("%1", snippet=None)
        capture_pane.assert_not_called()
        run_command.assert_not_called()

    def test_build_agent_command_uses_provider_specific_model_flag(self) -> None:
        command = build_agent_command(
            AgentConfig(
                role="coder",
                cli="kimi",
                model="kimi-2.5",
                model_flag="--model-name",
                args=["--sandbox", "workspace-write"],
            )
        )
        self.assertEqual(
            "kimi --model-name kimi-2.5 --sandbox workspace-write", command
        )

    def test_build_agent_command_omits_model_flag_when_none(self) -> None:
        cmd = build_agent_command(
            AgentConfig(
                role="coder",
                cli="opencode",
                model="opencode/qwen3-plus",
                model_flag=None,
                args=["--agent", "agentmux-coder"],
            )
        )
        self.assertIn("opencode", cmd)
        self.assertIn("--agent", cmd)
        self.assertNotIn("--model", cmd)
        self.assertNotIn("opencode/qwen3-plus", cmd)

    def test_build_agent_command_none_model_flag_no_extra_args(self) -> None:
        cmd = build_agent_command(
            AgentConfig(role="r", cli="opencode", model="m", model_flag=None)
        )
        self.assertEqual("opencode", cmd)

    def test_build_agent_command_includes_model_flag_when_set(self) -> None:
        cmd = build_agent_command(
            AgentConfig(role="r", cli="claude", model="sonnet", model_flag="--model")
        )
        self.assertIn("--model", cmd)
        self.assertIn("sonnet", cmd)

    def test_build_agent_command_includes_custom_model_flag(self) -> None:
        cmd = build_agent_command(
            AgentConfig(
                role="r", cli="kimi", model="kimi-2.5", model_flag="--model-name"
            )
        )
        self.assertIn("--model-name", cmd)
        self.assertIn("kimi-2.5", cmd)

    def test_batch_command_omits_model_flag_when_none(self) -> None:
        """When model_flag is None, batch command should NOT include --model."""
        cmd = build_agent_command(
            AgentConfig(
                role="code-researcher",
                cli="opencode",
                model="opencode/qwen3-plus",
                model_flag=None,
                batch_command=BatchCommand("run", BatchCommandMode.POSITIONAL),
                args=["--agent", "agentmux-researcher"],
            ),
            prompt_file="/tmp/prompt.md",
        )
        self.assertIn("opencode", cmd)
        self.assertIn("run", cmd)
        self.assertNotIn("--model", cmd)
        self.assertNotIn("opencode/qwen3-plus", cmd)
        self.assertIn("/tmp/prompt.md", cmd)
        self.assertIn("--agent", cmd)

    def test_batch_command_preserves_explicit_model_flag(self) -> None:
        """When model_flag is explicitly set, batch command should use it."""
        cmd = build_agent_command(
            AgentConfig(
                role="code-researcher",
                cli="claude",
                model="sonnet",
                model_flag="--model",
                args=["--agent", "agentmux-researcher"],
            ),
            prompt_file="/tmp/prompt.md",
        )
        self.assertIn("--model", cmd)
        self.assertIn("sonnet", cmd)
        self.assertIn("/tmp/prompt.md", cmd)

    def test_interactive_agent_excludes_batch_command(self) -> None:
        """Interactive agents (no prompt_file) must NOT include batch_command."""
        cmd = build_agent_command(
            AgentConfig(
                role="architect",
                cli="opencode",
                model="opencode/qwen3-plus",
                model_flag=None,
                batch_command=BatchCommand("run", BatchCommandMode.POSITIONAL),
                args=["--agent", "agentmux-architect"],
            )
        )
        # Should be: opencode --agent agentmux-architect
        # NOT: opencode run --agent agentmux-architect
        self.assertNotIn("run", cmd)
        self.assertIn("opencode", cmd)
        self.assertIn("--agent", cmd)
        self.assertIn("agentmux-architect", cmd)

    def test_batch_agent_includes_batch_command_with_prompt_file(self) -> None:
        """Batch agents (with prompt_file) MUST include batch_command."""
        cmd = build_agent_command(
            AgentConfig(
                role="code-researcher",
                cli="opencode",
                model="opencode/qwen3-plus",
                model_flag=None,
                batch_command=BatchCommand("run", BatchCommandMode.POSITIONAL),
                args=["--agent", "agentmux-code-researcher"],
            ),
            prompt_file="/tmp/prompt.md",
        )
        # Should be: opencode run --agent agentmux-code-researcher /tmp/prompt.md
        self.assertIn("run", cmd)
        self.assertIn("opencode", cmd)
        self.assertIn("/tmp/prompt.md", cmd)

    def test_opencode_architect_command_is_interactive(self) -> None:
        """Regression test: opencode architect must NOT use 'run' subcommand."""
        # This is the exact scenario that caused the orchestrator crash
        cmd = build_agent_command(
            AgentConfig(
                role="architect",
                cli="opencode",
                model="opencode/qwen3-plus",
                model_flag=None,
                batch_command=BatchCommand("run", BatchCommandMode.POSITIONAL),
                args=["--agent", "agentmux-architect"],
            )
        )
        # Must NOT contain 'run' - that's for batch mode only
        self.assertNotIn(" run ", f" {cmd} ")
        # Must be a valid interactive command
        self.assertTrue(cmd.startswith("opencode"))
        self.assertIn("--agent", cmd)

    def test_claude_architect_command_unaffected(self) -> None:
        """Claude architect should work as before (no batch_command)."""
        cmd = build_agent_command(
            AgentConfig(
                role="architect",
                cli="claude",
                model="sonnet",
                model_flag="--model",
                args=["--permission-mode", "acceptEdits"],
            )
        )
        self.assertIn("claude", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("sonnet", cmd)
        self.assertNotIn("run", cmd)

    def test_batch_command_none_with_prompt_file(self) -> None:
        """When batch_command is None, prompt_file is still appended."""
        cmd = build_agent_command(
            AgentConfig(
                role="researcher",
                cli="claude",
                model="sonnet",
                model_flag="--model",
                batch_command=None,
                args=[],
            ),
            prompt_file="/tmp/prompt.md",
        )
        self.assertIn("/tmp/prompt.md", cmd)
        self.assertNotIn(" run ", f" {cmd} ")

    def test_batch_command_flag_mode_places_prompt_right_after(self) -> None:
        """Flag-style batch_command (e.g. -p) puts prompt file right after it."""
        cmd = build_agent_command(
            AgentConfig(
                role="code-researcher",
                cli="copilot",
                model="claude-haiku",
                model_flag="--model",
                batch_command=BatchCommand("-p", BatchCommandMode.FLAG),
                args=["--allow-all", "--reasoning-effort", "high"],
            ),
            prompt_file="/tmp/prompt.md",
        )
        # Should be: copilot -p /tmp/prompt.md --model claude-haiku --allow-all ...
        self.assertIn("copilot", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("/tmp/prompt.md", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("claude-haiku", cmd)
        # Prompt must come right after -p, not at the end
        self.assertIn("-p /tmp/prompt.md", cmd)
        # Ensure prompt is not duplicated at the end
        parts = cmd.split()
        prompt_positions = [i for i, p in enumerate(parts) if "/tmp/prompt.md" in p]
        self.assertEqual(len(prompt_positions), 1)

    def test_gemini_batch_command_uses_prompt_flag(self) -> None:
        """Gemini batch command should use -p flag for prompt file."""
        cmd = build_agent_command(
            AgentConfig(
                role="web-researcher",
                cli="gemini",
                model="gemini-2.5-flash",
                model_flag="--model",
                batch_command=BatchCommand("-p", BatchCommandMode.FLAG),
                args=["--approval-mode", "yolo"],
            ),
            prompt_file="/tmp/prompt.md",
        )
        # gemini -p /tmp/prompt.md --model gemini-2.5-flash ...
        self.assertIn("gemini", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("/tmp/prompt.md", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("gemini-2.5-flash", cmd)
        self.assertIn("-p /tmp/prompt.md", cmd)
        # Ensure prompt is not duplicated at the end
        parts = cmd.split()
        prompt_positions = [i for i, p in enumerate(parts) if "/tmp/prompt.md" in p]
        self.assertEqual(len(prompt_positions), 1)

    def test_codex_batch_command_uses_stdin_redirect(self) -> None:
        """Codex exec batch command should use stdin redirect for prompt file."""
        cmd = build_agent_command(
            AgentConfig(
                role="code-researcher",
                cli="codex",
                model="o4-mini",
                model_flag="--model",
                batch_command=BatchCommand("exec", BatchCommandMode.STDIN),
                args=["-s", "workspace-write", "-a", "never"],
            ),
            prompt_file="/tmp/prompt.md",
        )
        # codex exec --model o4-mini ... < /tmp/prompt.md
        self.assertIn("codex", cmd)
        self.assertIn("exec", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("o4-mini", cmd)
        self.assertIn("/tmp/prompt.md", cmd)
        # Must use stdin redirect, not a positional arg
        self.assertIn("<", cmd)
        self.assertIn("< /tmp/prompt.md", cmd)
        # Ensure prompt appears only once (not as positional and not duplicated)
        parts = cmd.split()
        prompt_positions = [i for i, p in enumerate(parts) if "/tmp/prompt.md" in p]
        self.assertEqual(len(prompt_positions), 1)

    def test_accept_trust_prompt_accepts_when_snippet_is_present(self) -> None:
        commands: list[list[str]] = []

        with (
            patch(
                "agentmux.runtime.pane_io.capture_pane",
                side_effect=["some output", "Trust this folder?"],
            ),
            patch(
                "agentmux.runtime.pane_io.run_command",
                side_effect=lambda args, cwd=None, check=True: commands.append(args),
            ),
        ):
            accept_trust_prompt("%1", snippet="Trust this folder?", timeout_seconds=0.5)

        self.assertEqual(
            [
                ["tmux", "select-pane", "-t", "%1"],
                ["tmux", "send-keys", "-t", "%1", "Enter"],
            ],
            commands,
        )

    # New v2-specific tests
    def test_profile_key_in_v2_produces_error(self) -> None:
        """Using profile key in v2 config produces error."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = {
                "version": 2,
                "defaults": {"provider": "claude"},
                "roles": {"architect": {"profile": "max"}},  # profile not allowed in v2
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            with self.assertRaises(ValueError) as exc:
                load_explicit_config(cfg_path)

            self.assertIn("Profiles are not supported", str(exc.exception))

    def test_v2_config_parses_correctly(self) -> None:
        """v2 config with providers and model keys parses correctly."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = {
                "version": 2,
                "defaults": {"provider": "claude", "model": "sonnet"},
                "roles": {
                    "architect": {"model": "opus"},
                    "coder": {"provider": "codex", "model": "gpt-5.3-codex"},
                },
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)

            self.assertEqual("opus", loaded.agents["architect"].model)
            self.assertEqual("gpt-5.3-codex", loaded.agents["coder"].model)

    def test_direct_model_selection_per_role_works(self) -> None:
        """Roles can specify different models per provider."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = {
                "version": 2,
                "defaults": {"provider": "claude", "model": "sonnet"},
                "roles": {
                    "architect": {"model": "opus"},
                    "reviewer": {"model": "sonnet"},
                    "coder": {"provider": "codex", "model": "gpt-5.3-codex"},
                    "code-researcher": {"model": "haiku"},
                },
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)

            self.assertEqual("opus", loaded.agents["architect"].model)
            self.assertEqual("sonnet", loaded.agents["reviewer"].model)
            self.assertEqual("gpt-5.3-codex", loaded.agents["coder"].model)
            self.assertEqual("haiku", loaded.agents["code-researcher"].model)

    def test_unconfigured_roles_use_defaults(self) -> None:
        """Roles not explicitly configured should still be created with defaults."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yaml"
            cfg = {
                "version": 2,
                "defaults": {
                    "provider": "opencode",
                    "model": "fireworks-ai/accounts/fireworks/routers/kimi-k2p5-turbo",
                },
                "roles": {
                    "architect": {
                        "model": "fireworks-ai/accounts/fireworks/models/glm-5"
                    },
                },
            }
            cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)

            # Explicitly configured role uses its override
            self.assertEqual(
                "fireworks-ai/accounts/fireworks/models/glm-5",
                loaded.agents["architect"].model,
            )
            self.assertEqual("opencode", loaded.agents["architect"].provider)

            # Unconfigured roles should still exist with defaults
            self.assertIn("code-researcher", loaded.agents)
            self.assertIn("web-researcher", loaded.agents)
            self.assertIn("product-manager", loaded.agents)
            self.assertIn("reviewer", loaded.agents)
            self.assertIn("designer", loaded.agents)

            # Unconfigured roles use defaults
            self.assertEqual(
                "fireworks-ai/accounts/fireworks/routers/kimi-k2p5-turbo",
                loaded.agents["code-researcher"].model,
            )
            self.assertEqual("opencode", loaded.agents["code-researcher"].provider)
            self.assertEqual(
                "fireworks-ai/accounts/fireworks/routers/kimi-k2p5-turbo",
                loaded.agents["web-researcher"].model,
            )
            self.assertEqual("opencode", loaded.agents["web-researcher"].provider)

            # Coder also uses global defaults (no special built-in defaults)
            self.assertIn("coder", loaded.agents)
            self.assertEqual(
                "fireworks-ai/accounts/fireworks/routers/kimi-k2p5-turbo",
                loaded.agents["coder"].model,
            )
            self.assertEqual("opencode", loaded.agents["coder"].provider)

    def test_copilot_provider_has_default_model_and_role_args(self) -> None:
        """Copilot provider has default_model, default_role_args, model_args."""
        copilot = get_provider("copilot")
        self.assertEqual("claude-sonnet-4.6", copilot.default_model)
        self.assertEqual(["--allow-all"], copilot.default_role_args)
        self.assertIsNotNone(copilot.model_args)
        self.assertEqual(
            ["--reasoning-effort", "high"],
            copilot.model_args.get("claude-sonnet-4.6"),
        )

    def test_copilot_roles_inherit_default_role_args(self) -> None:
        """Copilot roles inherit default_role_args plus model_args."""
        copilot = get_provider("copilot")

        # Test with default model (claude-sonnet-4.6) – gets model_args appended
        for role in ["architect", "coder", "reviewer", "product-manager", "designer"]:
            agent = resolve_agent(
                global_provider=copilot,
                role=role,
                role_config={},  # No overrides
            )
            self.assertEqual(
                ["--allow-all", "--reasoning-effort", "high"],
                agent.args,
                f"Role {role} with sonnet model should include reasoning-effort",
            )
            self.assertEqual("claude-sonnet-4.6", agent.model)

    def test_role_args_can_extend_default_role_args(self) -> None:
        """Specific role_args can extend default_role_args."""
        with tempfile.TemporaryDirectory() as td:
            user_cfg_dir = Path(td) / "user"
            user_cfg_dir.mkdir()
            user_cfg_path = user_cfg_dir / "config.yaml"
            user_cfg_path.write_text(
                """
version: 2
providers:
  test_provider:
    command: test
    model_flag: --model
    default_role_args:
    - --default-flag
    - default-value
    role_args:
      coder:
      - --specific-flag
      - specific-value
roles:
  coder:
    provider: test_provider
    model: test-model
""".strip()
                + "\n",
                encoding="utf-8",
            )
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            with patch("agentmux.configuration.USER_CONFIG_PATH", user_cfg_path):
                loaded = load_layered_config(project_dir)

            coder = loaded.agents["coder"]
            # Should have both default and specific args
            self.assertEqual(
                [
                    "--default-flag",
                    "default-value",
                    "--specific-flag",
                    "specific-value",
                ],
                coder.args,
            )

    def test_provider_default_model_used_when_no_role_model(self) -> None:
        """Provider default_model should be used when role has no model override."""
        copilot = get_provider("copilot")
        agent = resolve_agent(
            global_provider=copilot,
            role="coder",
            role_config={},  # No model specified
        )
        self.assertEqual("claude-sonnet-4.6", agent.model)

    def test_model_args_appended_for_matching_model(self) -> None:
        """model_args should be appended when model matches."""
        copilot = get_provider("copilot")
        agent = resolve_agent(
            global_provider=copilot,
            role="web-researcher",
            role_config={"model": "claude-sonnet-4.6"},
        )
        self.assertEqual(
            ["--allow-all", "--reasoning-effort", "high"],
            agent.args,
        )

    def test_model_args_not_appended_for_non_matching_model(self) -> None:
        """model_args should NOT be appended when model has no entry."""
        copilot = get_provider("copilot")
        agent = resolve_agent(
            global_provider=copilot,
            role="web-researcher",
            role_config={"model": "claude-haiku-4.5"},
        )
        # Haiku has no model_args entry, so only default_role_args should be present
        self.assertEqual(
            ["--allow-all"],
            agent.args,
        )

    def test_role_model_overrides_provider_default_model(self) -> None:
        """Role-specific model should override provider default_model."""
        copilot = get_provider("copilot")
        agent = resolve_agent(
            global_provider=copilot,
            role="coder",
            role_config={"model": "custom-model"},
        )
        self.assertEqual("custom-model", agent.model)

    def test_qwen_provider_loads(self):
        p = PROVIDERS["qwen"]
        self.assertEqual("qwen", p.cli)
        self.assertIsNone(p.model_flag)
        self.assertIsNone(p.trust_snippet)
        self.assertEqual("qwen3-max", p.default_model)
        self.assertEqual(["--yolo"], p.default_role_args)

    def test_qwen_resolve_agent(self):
        agent = resolve_agent(
            global_provider=get_provider("qwen"),
            role="coder",
            role_config={},
        )
        self.assertEqual("qwen", agent.cli)
        self.assertIsNone(agent.model_flag)
        self.assertIsNone(agent.trust_snippet)
        self.assertIn("--yolo", agent.args)

    def test_qwen_build_agent_command(self):
        agent = AgentConfig(
            role="coder",
            cli="qwen",
            model="qwen3-max",
            model_flag=None,
            args=["--yolo"],
        )
        cmd = build_agent_command(agent)
        self.assertIn("qwen", cmd)
        self.assertIn("--yolo", cmd)
        self.assertNotIn("--model", cmd)


if __name__ == "__main__":
    unittest.main()
