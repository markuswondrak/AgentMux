"""Integration tests for v2 config schema and migration path."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agentmux.configuration import load_explicit_config, load_layered_config
from agentmux.pipeline.init_command import generate_config, validate_config


class V2ConfigIntegrationTests(unittest.TestCase):
    """End-to-end tests for v2 configuration schema."""

    def test_init_defaults_generates_valid_v2_config(self) -> None:
        """Test: `agentmux init --defaults` generates valid v2 config."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            # Generate config with defaults mode
            config_path = generate_config(
                {}, project_dir, console=None, defaults_mode=True
            )

            # Verify file was created
            self.assertTrue(config_path.exists())
            self.assertEqual(config_path, project_dir / ".agentmux" / "config.yaml")

            # Parse and verify structure
            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["version"], 2)
            self.assertNotIn("profile", parsed.get("defaults", {}))

            # Verify it passes validation
            with patch(
                "agentmux.configuration.USER_CONFIG_PATH", Path(td) / "nonexistent.yaml"
            ):
                self.assertTrue(validate_config(project_dir, console=None))

            # Verify it can be loaded
            with patch(
                "agentmux.configuration.USER_CONFIG_PATH", Path(td) / "nonexistent.yaml"
            ):
                loaded = load_layered_config(project_dir)
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.session_name, "multi-agent-mvp")

    def test_init_with_overrides_generates_valid_v2_config(self) -> None:
        """Test: `agentmux init` with overrides generates valid v2 config."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            # Simulate overrides from interactive mode
            overrides = {
                "defaults": {"provider": "claude"},
                "roles": {
                    "architect": {"model": "opus"},
                    "coder": {"provider": "codex", "model": "gpt-5.3-codex"},
                },
            }

            config_path = generate_config(
                overrides, project_dir, console=None, defaults_mode=True
            )

            # Verify structure
            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["version"], 2)
            self.assertEqual(parsed["defaults"]["provider"], "claude")
            self.assertEqual(parsed["roles"]["architect"]["model"], "opus")
            self.assertEqual(parsed["roles"]["coder"]["provider"], "codex")
            self.assertEqual(parsed["roles"]["coder"]["model"], "gpt-5.3-codex")

            # Verify it loads correctly
            with patch(
                "agentmux.configuration.USER_CONFIG_PATH", Path(td) / "nonexistent.yaml"
            ):
                loaded = load_layered_config(project_dir)
                self.assertIn("architect", loaded.agents)
                self.assertIn("coder", loaded.agents)
                self.assertEqual(loaded.agents["architect"].model, "opus")
                self.assertEqual(loaded.agents["coder"].model, "gpt-5.3-codex")

    def test_v2_config_with_profile_key_produces_error(self) -> None:
        """Test: Using profile key in config produces error."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = {
                "version": 2,
                "defaults": {"provider": "claude"},
                "roles": {
                    "architect": {"profile": "max"},  # profile not allowed
                },
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            with self.assertRaises(ValueError) as exc:
                load_explicit_config(cfg_path)

            self.assertIn("Profiles are not supported", str(exc.exception))

    def test_custom_provider_in_project_config_works(self) -> None:
        """Test: Custom provider defined in project config works."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)

            # Create project config with custom provider
            v2_config = {
                "version": 2,
                "providers": {
                    "kimi": {
                        "command": "kimi",
                        "model_flag": "--model-name",
                        "role_args": {
                            "coder": ["--sandbox", "workspace-write"],
                        },
                    },
                },
                "roles": {
                    "coder": {
                        "provider": "kimi",
                        "model": "kimi-2.5",
                    },
                },
            }

            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                yaml.safe_dump(v2_config, sort_keys=False),
                encoding="utf-8",
            )

            # Should load without error
            with patch(
                "agentmux.configuration.USER_CONFIG_PATH", Path(td) / "nonexistent.yaml"
            ):
                loaded = load_layered_config(project_dir)

                # Verify custom provider works
                self.assertIn("coder", loaded.agents)
                self.assertEqual(loaded.agents["coder"].cli, "kimi")
                self.assertEqual(loaded.agents["coder"].model, "kimi-2.5")
                self.assertEqual(loaded.agents["coder"].model_flag, "--model-name")

    def test_direct_model_selection_without_profiles(self) -> None:
        """Test: User can specify model directly without profile mappings."""
        with tempfile.TemporaryDirectory() as td:
            # User specifies model directly
            config = {
                "version": 2,
                "defaults": {"provider": "claude", "model": "sonnet"},
                "roles": {
                    "architect": {"model": "opus"},
                    "reviewer": {"model": "sonnet"},
                    "coder": {"provider": "codex", "model": "gpt-5.1-codex-mini"},
                },
            }

            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(config), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)

            # All models should be exactly as specified
            self.assertEqual(loaded.agents["architect"].model, "opus")
            self.assertEqual(loaded.agents["reviewer"].model, "sonnet")
            self.assertEqual(loaded.agents["coder"].model, "gpt-5.1-codex-mini")

    def test_no_profile_terminology_in_error_messages(self) -> None:
        """Test: No profile-related terminology in codebase error messages."""
        with tempfile.TemporaryDirectory() as td:
            # Test unknown provider error
            config = {
                "version": 2,
                "roles": {
                    "coder": {"provider": "unknown-provider", "model": "test"},
                },
            }

            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(config), encoding="utf-8")

            try:
                load_explicit_config(cfg_path)
                self.fail("Should have raised ValueError")
            except ValueError as e:
                error_msg = str(e)
                # Should reference "provider" not "profile"
                self.assertIn("provider", error_msg.lower())
                self.assertNotIn("profile", error_msg.lower())


class V2ConfigLayeredLoadingTests(unittest.TestCase):
    """Test layered config loading with v2 schema."""

    def test_project_config_can_override_all_layers(self) -> None:
        """Test: Project config can define providers (Full Override Capability)."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            # Create project config with custom provider
            project_config = {
                "version": 2,
                "providers": {
                    "custom": {
                        "command": "custom-cli",
                        "model_flag": "--model",
                    },
                },
                "roles": {
                    "architect": {"provider": "custom", "model": "custom-model"},
                },
            }

            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                yaml.safe_dump(project_config, sort_keys=False),
                encoding="utf-8",
            )

            # Mock user config to not exist
            with patch(
                "agentmux.configuration.USER_CONFIG_PATH", Path(td) / "nonexistent.yaml"
            ):
                loaded = load_layered_config(project_dir)

                # Project provider should be available
                self.assertIn("architect", loaded.agents)
                self.assertEqual(loaded.agents["architect"].cli, "custom-cli")
                self.assertEqual(loaded.agents["architect"].provider, "custom")


class V2ConfigNullableModelFlagTests(unittest.TestCase):
    """Sub-plan 2: nullable model_flag through config resolution pipeline."""

    def test_opencode_provider_produces_null_model_flag(self) -> None:
        """When opencode is the default provider, all roles should have model_flag=None."""  # noqa: E501
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yaml"
            cfg = {
                "version": 2,
                "defaults": {
                    "provider": "opencode",
                    "model": "some-model",
                },
            }
            cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)
            self.assertIsNone(loaded.agents["coder"].model_flag)
            self.assertIsNone(loaded.agents["architect"].model_flag)

    def test_claude_provider_retains_model_flag(self) -> None:
        """When claude is the provider, all roles should have model_flag='--model'."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yaml"
            cfg = {
                "version": 2,
                "defaults": {
                    "provider": "claude",
                    "model": "sonnet",
                },
            }
            cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)
            self.assertEqual("--model", loaded.agents["coder"].model_flag)
            self.assertEqual("--model", loaded.agents["architect"].model_flag)

    def test_explicit_null_model_flag_in_yaml(self) -> None:
        """A custom provider with model_flag: null should produce None."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yaml"
            cfg = {
                "version": 2,
                "providers": {
                    "custom": {
                        "command": "custom-cli",
                        "model_flag": None,
                        "role_args": {},
                    },
                },
                "roles": {
                    "coder": {"provider": "custom", "model": "custom-model"},
                },
            }
            cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)
            self.assertIsNone(loaded.agents["coder"].model_flag)

    def test_explicit_model_flag_value_is_preserved(self) -> None:
        """A custom provider with model_flag: --model-name should preserve it."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yaml"
            cfg = {
                "version": 2,
                "providers": {
                    "custom": {
                        "command": "custom-cli",
                        "model_flag": "--model-name",
                        "role_args": {},
                    },
                },
                "roles": {
                    "coder": {"provider": "custom", "model": "custom-model"},
                },
            }
            cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)
            self.assertEqual("--model-name", loaded.agents["coder"].model_flag)

    def test_absent_model_flag_normalizes_to_none(self) -> None:
        """A custom provider with no model_flag key should produce None."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.yaml"
            cfg = {
                "version": 2,
                "providers": {
                    "custom": {
                        "command": "custom-cli",
                        "role_args": {},
                    },
                },
                "roles": {
                    "coder": {"provider": "custom", "model": "custom-model"},
                },
            }
            cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

            loaded = load_explicit_config(cfg_path)
            self.assertIsNone(loaded.agents["coder"].model_flag)


if __name__ == "__main__":
    unittest.main()
