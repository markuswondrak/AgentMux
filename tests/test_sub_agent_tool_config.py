"""Tests for sub_agent_tool on Provider and AgentConfig (config propagation)."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agentmux.configuration import load_explicit_config
from agentmux.configuration.providers import get_provider, resolve_agent


class SubAgentToolConfigTests(unittest.TestCase):
    def test_builtin_provider_defaults_sub_agent_tool_to_none(self) -> None:
        self.assertIsNone(get_provider("claude").sub_agent_tool)

    def test_copilot_builtin_provider_has_sub_agent_tool_task(self) -> None:
        self.assertEqual(get_provider("copilot").sub_agent_tool, "task")

    def test_resolve_agent_propagates_sub_agent_tool_from_provider(self) -> None:
        base = get_provider("claude")
        provider = replace(base, sub_agent_tool="mcp__example__dispatch")
        agent = resolve_agent(provider, "coder", {})
        self.assertEqual(agent.sub_agent_tool, "mcp__example__dispatch")

    def test_load_explicit_config_merges_sub_agent_tool_into_agents(self) -> None:
        """Merged provider dict exposes sub_agent_tool on each AgentConfig."""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg = {
                "version": 2,
                "providers": {
                    "claude": {
                        "sub_agent_tool": "mcp__project__subagent_run",
                    },
                },
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            with patch(
                "agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing.yaml"
            ):
                loaded = load_explicit_config(cfg_path)

            self.assertEqual(
                loaded.agents["coder"].sub_agent_tool,
                "mcp__project__subagent_run",
            )
