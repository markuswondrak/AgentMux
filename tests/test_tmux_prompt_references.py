from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agentmux.shared.models import AgentConfig
from agentmux.runtime.tmux_control import ContentZone
from agentmux.runtime.tmux_control import MONITOR_MAX_WIDTH
from agentmux.runtime.tmux_control import MONITOR_MIN_WIDTH
from agentmux.runtime.tmux_control import _enforce_monitor_min_width
from agentmux.runtime.tmux_control import create_agent_pane
from agentmux.runtime.tmux_control import send_prompt
from agentmux.runtime.tmux_control import set_pane_identity
from agentmux.runtime.tmux_control import tmux_pane_exists
from agentmux.runtime.tmux_control import tmux_new_session


class TmuxPromptReferencesTests(unittest.TestCase):
    def test_send_prompt_sends_reference_message_not_full_prompt_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            prompt_file = Path(td) / "coder_prompt.md"
            prompt_file.write_text("line 1\\nline 2\\n", encoding="utf-8")
            sent: list[str] = []

            with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True), patch(
                "agentmux.runtime.tmux_control.send_text", side_effect=lambda _pane, text: sent.append(text)
            ):
                send_prompt("%1", prompt_file)

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

            with patch("agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command), patch(
                "agentmux.runtime.tmux_control._enforce_monitor_min_width", return_value=None
            ), patch("agentmux.runtime.tmux_control.accept_trust_prompt", return_value=None):
                panes, _zone = tmux_new_session(
                    "session-x",
                    agents,
                    feature_dir,
                    config_path,
                    trust_snippet=None,
                )

            border_status_cmd = ["tmux", "set-option", "-t", "session-x", "pane-border-status", "top"]
            border_format_cmd = next(
                cmd
                for cmd in commands
                if cmd[:5] == ["tmux", "set-option", "-t", "session-x", "pane-border-format"]
            )
            self.assertEqual("%1", panes["architect"])
            self.assertIn(border_status_cmd, commands)
            self.assertIn("#{@pane_label}", border_format_cmd[5])
            self.assertIn("#{@role}", border_format_cmd[5])
            self.assertNotIn(",,", border_format_cmd[5])
            self.assertIn("#{?#{@pane_label},", border_format_cmd[5])
            self.assertNotIn("·", border_format_cmd[5])
            split_index = commands.index(next(cmd for cmd in commands if cmd[:2] == ["tmux", "split-window"]))
            self.assertLess(commands.index(border_status_cmd), split_index)
            self.assertLess(commands.index(border_format_cmd), split_index)

    def test_enforce_monitor_min_width_resizes_when_monitor_is_too_narrow(self) -> None:
        commands: list[list[str]] = []

        def fake_run_command(args, cwd=None, check=True):
            _ = (cwd, check)
            commands.append(list(args))
            if args[:4] == ["tmux", "display-message", "-p", "-t"] and args[-1] == "#{pane_width}":
                return CompletedProcess(args=args, returncode=0, stdout="18\n", stderr="")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with patch("agentmux.runtime.tmux_control._find_control_pane", return_value="%0"), patch(
            "agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command
        ):
            _enforce_monitor_min_width("session-x")

        self.assertIn(
            ["tmux", "resize-pane", "-t", "%0", "-x", str(MONITOR_MIN_WIDTH)],
            commands,
        )

    def test_enforce_monitor_min_width_resizes_when_monitor_is_too_wide(self) -> None:
        commands: list[list[str]] = []

        def fake_run_command(args, cwd=None, check=True):
            _ = (cwd, check)
            commands.append(list(args))
            if args[:4] == ["tmux", "display-message", "-p", "-t"] and args[-1] == "#{pane_width}":
                return CompletedProcess(args=args, returncode=0, stdout="52\n", stderr="")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with patch("agentmux.runtime.tmux_control._find_control_pane", return_value="%0"), patch(
            "agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command
        ):
            _enforce_monitor_min_width("session-x")

        self.assertIn(
            ["tmux", "resize-pane", "-t", "%0", "-x", str(MONITOR_MAX_WIDTH)],
            commands,
        )

    def test_content_zone_show_reapplies_monitor_min_width(self) -> None:
        with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True):
            zone = ContentZone("session-x", placeholder="%9")

        with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True), patch(
            "agentmux.runtime.tmux_control.run_command", return_value=CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        ), patch("agentmux.runtime.tmux_control._enforce_monitor_min_width") as width_mock, patch(
            "agentmux.runtime.tmux_control._log_layout", return_value=None
        ):
            zone.show("%1")

        width_mock.assert_called_once_with("session-x")

    def test_content_zone_show_parallel_rebalances_visible_content_panes(self) -> None:
        commands: list[list[str]] = []

        def fake_run_command(args, cwd=None, check=True):
            _ = (cwd, check)
            commands.append(list(args))
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True):
            zone = ContentZone("session-x", visible=["%1"], placeholder="%9")

        with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True), patch(
            "agentmux.runtime.tmux_control._pane_in_window",
            side_effect=lambda pane_id, window_name: window_name == "pipeline" and pane_id != "%9",
        ), patch("agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command), patch(
            "agentmux.runtime.tmux_control._enforce_monitor_min_width"
        ) as width_mock, patch("agentmux.runtime.tmux_control._log_layout", return_value=None):
            zone.show_parallel(["%1", "%2", "%3"])

        self.assertEqual(
            [
                ["tmux", "join-pane", "-v", "-s", "%2", "-t", "%1"],
                ["tmux", "join-pane", "-v", "-s", "%3", "-t", "%1"],
                ["tmux", "select-layout", "-E", "-t", "%1"],
            ],
            [cmd for cmd in commands if cmd[:2] in (["tmux", "join-pane"], ["tmux", "select-layout"])],
        )
        width_mock.assert_called_once_with("session-x")

    def test_content_zone_hide_rebalances_remaining_visible_panes(self) -> None:
        commands: list[list[str]] = []

        def fake_run_command(args, cwd=None, check=True):
            _ = (cwd, check)
            commands.append(list(args))
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True):
            zone = ContentZone("session-x", visible=["%1", "%2", "%3"], placeholder="%9")

        with patch("agentmux.runtime.tmux_control.tmux_pane_exists", return_value=True), patch(
            "agentmux.runtime.tmux_control._pane_in_window",
            side_effect=lambda pane_id, window_name: window_name == "pipeline" and pane_id != "%9",
        ), patch("agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command), patch(
            "agentmux.runtime.tmux_control._enforce_monitor_min_width"
        ) as width_mock, patch("agentmux.runtime.tmux_control._log_layout", return_value=None):
            zone.hide("%2")

        self.assertEqual(["%1", "%3"], zone.visible)
        self.assertEqual(
            [
                ["tmux", "break-pane", "-d", "-s", "%2", "-n", "_hidden"],
                ["tmux", "select-layout", "-E", "-t", "%1"],
            ],
            [cmd for cmd in commands if cmd[:2] in (["tmux", "break-pane"], ["tmux", "select-layout"])],
        )
        width_mock.assert_called_once_with("session-x")

    def test_set_pane_identity_keeps_role_and_sets_display_label(self) -> None:
        commands: list[list[str]] = []

        def fake_run_command(args, cwd=None, check=True):
            _ = (cwd, check)
            commands.append(list(args))
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with patch("agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command):
            set_pane_identity("%7", role="coder", display_label="API wiring")

        self.assertEqual(
            [
                ["tmux", "select-pane", "-t", "%7", "-T", "API wiring"],
                ["tmux", "set-option", "-p", "-t", "%7", "@role", "coder"],
                ["tmux", "set-option", "-p", "-t", "%7", "@pane_label", "API wiring"],
            ],
            commands,
        )

    def test_create_agent_pane_applies_display_label_without_overwriting_role(self) -> None:
        agents = {
            "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
        }
        commands: list[list[str]] = []

        def fake_run_command(args, cwd=None, check=True):
            _ = (cwd, check)
            commands.append(list(args))
            if args[:2] == ["tmux", "split-window"]:
                return CompletedProcess(args=args, returncode=0, stdout="%9\n", stderr="")
            return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with patch("agentmux.runtime.tmux_control._find_any_hidden_pane", return_value="%2"), patch(
            "agentmux.runtime.tmux_control._pane_in_window", return_value=False
        ), patch("agentmux.runtime.tmux_control.accept_trust_prompt", return_value=None), patch(
            "agentmux.runtime.tmux_control.time.sleep", return_value=None
        ), patch("agentmux.runtime.tmux_control.run_command", side_effect=fake_run_command):
            pane_id = create_agent_pane(
                "session-x",
                "coder",
                agents,
                trust_snippet=None,
                display_label="API wiring",
            )

        self.assertEqual("%9", pane_id)
        self.assertIn(["tmux", "set-option", "-p", "-t", "%9", "@role", "coder"], commands)
        self.assertIn(["tmux", "set-option", "-p", "-t", "%9", "@pane_label", "API wiring"], commands)

    def test_tmux_pane_exists_returns_false_for_dead_pane(self) -> None:
        with patch(
            "agentmux.runtime.tmux_control.run_command",
            return_value=CompletedProcess(args=[], returncode=0, stdout="%1 1\n", stderr=""),
        ):
            self.assertFalse(tmux_pane_exists("%1"))

    def test_tmux_pane_exists_returns_true_for_live_pane(self) -> None:
        with patch(
            "agentmux.runtime.tmux_control.run_command",
            return_value=CompletedProcess(args=[], returncode=0, stdout="%1 0\n", stderr=""),
        ):
            self.assertTrue(tmux_pane_exists("%1"))


if __name__ == "__main__":
    unittest.main()
