"""Sub-plan 1: Data Models, YAML & Provider Type Changes.

Tests for making model_flag nullable (str | None) so that opencode
does not receive a --model flag it does not support.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from agentmux.configuration.providers import PROVIDERS, get_provider, resolve_agent
from agentmux.shared.models import AgentConfig


class TestAgentConfigModelFlagNullable(unittest.TestCase):
    """Task 1.1 — AgentConfig.model_flag type is str | None."""

    def test_model_flag_defaults_to_dash_model(self) -> None:
        """Default model_flag should be '--model' for backward compat."""
        agent = AgentConfig(role="r", cli="c", model="m")
        self.assertEqual("--model", agent.model_flag)

    def test_model_flag_can_be_none(self) -> None:
        """model_flag should accept None explicitly."""
        agent = AgentConfig(role="r", cli="c", model="m", model_flag=None)
        self.assertIsNone(agent.model_flag)


class TestBuiltinCatalogOpencodeNoModelFlag(unittest.TestCase):
    """Task 1.2 — opencode provider has no model_flag in built-in YAML."""

    def test_opencode_has_no_model_flag_key(self) -> None:
        """The opencode provider block should not contain model_flag."""
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
        opencode = config["providers"]["opencode"]
        self.assertNotIn("model_flag", opencode)

    def test_claude_retains_model_flag(self) -> None:
        """Other providers (claude) must retain their model_flag."""
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
        claude = config["providers"]["claude"]
        self.assertEqual("--model", claude["model_flag"])


class TestProviderModelFlagType(unittest.TestCase):
    """Task 1.3 & 1.4 — Provider.model_flag is str | None and preserves None."""

    def test_opencode_provider_model_flag_is_none(self) -> None:
        """PROVIDERS['opencode'].model_flag should be None."""
        self.assertIsNone(PROVIDERS["opencode"].model_flag)

    def test_claude_provider_model_flag_is_dash_model(self) -> None:
        """PROVIDERS['claude'].model_flag should be '--model'."""
        self.assertEqual("--model", PROVIDERS["claude"].model_flag)

    def test_codex_provider_model_flag_is_dash_model(self) -> None:
        """PROVIDERS['codex'].model_flag should be '--model'."""
        self.assertEqual("--model", PROVIDERS["codex"].model_flag)

    def test_gemini_provider_model_flag_is_dash_model(self) -> None:
        """PROVIDERS['gemini'].model_flag should be '--model'."""
        self.assertEqual("--model", PROVIDERS["gemini"].model_flag)

    def test_copilot_provider_model_flag_is_dash_model(self) -> None:
        """PROVIDERS['copilot'].model_flag should be '--model'."""
        self.assertEqual("--model", PROVIDERS["copilot"].model_flag)


class TestResolveAgentPropagatesNone(unittest.TestCase):
    """Task 1.5 — resolve_agent propagates None without str() coercion."""

    def test_resolve_agent_opencode_has_none_model_flag(self) -> None:
        """resolve_agent for opencode should return AgentConfig with model_flag=None."""
        agent = resolve_agent(
            global_provider=get_provider("opencode"),
            role="coder",
            role_config={},
        )
        self.assertIsNone(agent.model_flag)

    def test_resolve_agent_claude_has_dash_model_model_flag(self) -> None:
        """resolve_agent for claude should return AgentConfig with model_flag='--model'."""  # noqa: E501
        agent = resolve_agent(
            global_provider=get_provider("claude"),
            role="coder",
            role_config={},
        )
        self.assertEqual("--model", agent.model_flag)


if __name__ == "__main__":
    unittest.main()
