from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
from src.providers import PROVIDERS, get_provider, resolve_agent
from src.tmux import accept_trust_prompt


class ProviderAbstractionTests(unittest.TestCase):
    def test_get_provider_rejects_unknown_name(self) -> None:
        with self.assertRaises(ValueError):
            get_provider("unknown-provider")

    def test_resolve_agent_uses_role_provider_tier_and_args_override(self) -> None:
        agent = resolve_agent(
            global_provider=get_provider("claude"),
            role="coder",
            role_config={"provider": "codex", "tier": "low", "args": ["--x"]},
        )
        self.assertEqual("coder", agent.role)
        self.assertEqual(PROVIDERS["codex"].cli, agent.cli)
        self.assertEqual("gpt-5.1-codex-mini", agent.model)
        self.assertEqual(["--x"], agent.args)
        self.assertIsNone(agent.trust_snippet)

    def test_load_config_resolves_global_provider_defaults_and_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "pipeline_config.json"
            cfg = {
                "session_name": "s",
                "provider": "claude",
                "architect": {"tier": "max"},
                "coder": {"provider": "codex", "tier": "standard"},
                "docs": {"tier": "low"},
            }
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            session_name, agents, max_review_iterations = pipeline.load_config(cfg_path)

            self.assertEqual("s", session_name)
            self.assertEqual(3, max_review_iterations)
            self.assertEqual("claude", agents["architect"].cli)
            self.assertEqual("opus", agents["architect"].model)
            self.assertEqual("codex", agents["coder"].cli)
            self.assertEqual("codex-mini-latest", agents["coder"].model)
            self.assertEqual("claude", agents["docs"].cli)
            self.assertEqual("haiku", agents["docs"].model)

    def test_accept_trust_prompt_skips_when_no_snippet(self) -> None:
        with patch("src.tmux.capture_pane") as capture_pane, patch("src.tmux.run_command") as run_command:
            accept_trust_prompt("%1", snippet=None)
        capture_pane.assert_not_called()
        run_command.assert_not_called()

    def test_accept_trust_prompt_accepts_when_snippet_is_present(self) -> None:
        commands: list[list[str]] = []

        with patch(
            "src.tmux.capture_pane",
            side_effect=["some output", "Trust this folder?"],
        ), patch(
            "src.tmux.run_command",
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
