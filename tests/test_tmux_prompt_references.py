from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agentmux.models import AgentConfig
from agentmux.tmux import send_prompt
from agentmux.tmux import tmux_new_session


class TmuxPromptReferencesTests(unittest.TestCase):
    def test_send_prompt_sends_reference_message_not_full_prompt_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            prompt_file = Path(td) / "coder_prompt.md"
            prompt_file.write_text("line 1\\nline 2\\n", encoding="utf-8")
            sent: list[str] = []

            with patch("agentmux.tmux.tmux_pane_exists", return_value=True), patch(
                "agentmux.tmux.show_agent_pane", return_value=None
            ), patch("agentmux.tmux.send_text", side_effect=lambda _pane, text: sent.append(text)):
                send_prompt("%1", prompt_file, session_name="session-x")

            self.assertEqual(1, len(sent))
            self.assertEqual(
                f"Read and follow the instructions in {prompt_file.resolve()}",
                sent[0],
            )
            self.assertNotIn("line 1", sent[0])

    def test_tmux_new_session_enables_pane_border_titles(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            config_path = Path(td) / "pipeline_config.json"
            feature_dir.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{}", encoding="utf-8")
            agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
                "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
            }

            commands: list[list[str]] = []
            split_count = 0

            def fake_run_command(args, cwd=None, check=True):
                nonlocal split_count
                _ = (cwd, check)
                commands.append(list(args))
                if args[:2] == ["tmux", "new-session"]:
                    return CompletedProcess(args=args, returncode=0, stdout="%0\n", stderr="")
                if args[:2] == ["tmux", "split-window"]:
                    split_count += 1
                    pane = "%1" if split_count == 1 else "%2"
                    return CompletedProcess(args=args, returncode=0, stdout=f"{pane}\n", stderr="")
                return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with patch("agentmux.tmux.run_command", side_effect=fake_run_command), patch(
                "agentmux.tmux._fix_control_width", return_value=None
            ), patch("agentmux.tmux.accept_trust_prompt", return_value=None):
                tmux_new_session("session-x", agents, feature_dir, config_path, trust_snippet=None)

            border_status_cmd = ["tmux", "set-option", "-t", "session-x", "pane-border-status", "top"]
            border_format_cmd = next(
                cmd
                for cmd in commands
                if cmd[:5] == ["tmux", "set-option", "-t", "session-x", "pane-border-format"]
            )
            self.assertIn(border_status_cmd, commands)
            self.assertIn("#{pane_title}", border_format_cmd[5])
            split_index = commands.index(next(cmd for cmd in commands if cmd[:2] == ["tmux", "split-window"]))
            self.assertLess(commands.index(border_status_cmd), split_index)
            self.assertLess(commands.index(border_format_cmd), split_index)


if __name__ == "__main__":
    unittest.main()
