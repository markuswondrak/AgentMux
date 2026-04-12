from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agentmux.pipeline as pipeline
import agentmux.pipeline.application as application
from agentmux.runtime.tmux_control import kill_agentmux_session
from agentmux.sessions import SessionRecord, SessionService
from agentmux.sessions.state_store import cleanup_feature_dir, write_state
from agentmux.terminal_ui.console import ConsoleUI
from agentmux.terminal_ui.screens import goodbye_canceled, goodbye_error
from agentmux.workflow.interruptions import InterruptionService


class KillAgentmuxSessionTests(unittest.TestCase):
    def test_kill_agentmux_session_returns_true_on_success(self) -> None:
        with patch(
            "agentmux.runtime.tmux_control.run_command",
            return_value=SimpleNamespace(returncode=0),
        ) as mock_run:
            result = kill_agentmux_session("agentmux-test-session")
            self.assertTrue(result)
            mock_run.assert_called_once_with(
                ["tmux", "kill-session", "-t", "agentmux-test-session"],
                check=False,
            )

    def test_kill_agentmux_session_returns_false_on_failure(self) -> None:
        with patch(
            "agentmux.runtime.tmux_control.run_command",
            return_value=SimpleNamespace(returncode=1),
        ) as mock_run:
            result = kill_agentmux_session("agentmux-test-session")
            self.assertFalse(result)
            mock_run.assert_called_once()


class RemoveAllSessionsTests(unittest.TestCase):
    def test_remove_all_sessions_kills_tmux_and_removes_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            service = SessionService(project_dir)
            root = service.root_dir()

            # Create session directories with state files
            session1 = root / "20260101-100000-session1"
            session2 = root / "20260101-200000-session2"
            session1.mkdir(parents=True)
            session2.mkdir(parents=True)
            write_state(session1 / "state.json", {"phase": "planning"})
            write_state(session2 / "state.json", {"phase": "implementing"})

            with (
                patch(
                    "agentmux.runtime.tmux_control.kill_agentmux_session",
                    return_value=True,
                ) as mock_kill,
                patch(
                    "agentmux.runtime.tmux_core.tmux_session_exists",
                    return_value=True,
                ),
            ):
                count = service.remove_all_sessions(kill_tmux=True)

            self.assertEqual(2, count)
            self.assertFalse(session1.exists())
            self.assertFalse(session2.exists())
            # Verify kill was called for each session
            self.assertEqual(2, mock_kill.call_count)

    def test_remove_all_sessions_skips_kill_when_kill_tmux_false(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            service = SessionService(project_dir)
            root = service.root_dir()

            session1 = root / "20260101-100000-session1"
            session1.mkdir(parents=True)
            write_state(session1 / "state.json", {"phase": "planning"})

            with patch(
                "agentmux.runtime.tmux_control.kill_agentmux_session",
                return_value=True,
            ) as mock_kill:
                count = service.remove_all_sessions(kill_tmux=False)

            self.assertEqual(1, count)
            self.assertFalse(session1.exists())
            mock_kill.assert_not_called()

    def test_remove_all_sessions_returns_zero_when_no_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            service = SessionService(project_dir)
            count = service.remove_all_sessions()
            self.assertEqual(0, count)


class PrintSessionListTests(unittest.TestCase):
    def test_print_session_list_shows_tabular_output(self) -> None:
        output_lines: list[str] = []
        ui = ConsoleUI(output_fn=output_lines.append)

        sessions = [
            SessionRecord(
                Path("/tmp/20260101-100000-session1"),
                {
                    "phase": "planning",
                    "updated_at": "2026-01-01T10:00:00+01:00",
                },
            ),
            SessionRecord(
                Path("/tmp/20260101-090000-session2"),
                {
                    "phase": "completed",
                    "updated_at": "2026-01-01T09:00:00+01:00",
                },
            ),
        ]
        active_tmux = ["agentmux-20260101-100000-session1"]

        ui.print_session_list(sessions, active_tmux)

        output = "\n".join(output_lines)
        self.assertIn("ID", output)
        self.assertIn("phase", output)
        self.assertIn("status", output)
        self.assertIn("updated", output)
        self.assertIn("20260101-100000-session1", output)
        self.assertIn("20260101-090000-session2", output)
        self.assertIn("running", output)
        self.assertIn("stopped", output)

    def test_print_session_list_shows_message_when_empty(self) -> None:
        output_lines: list[str] = []
        ui = ConsoleUI(output_fn=output_lines.append)

        ui.print_session_list([], [])

        output = "\n".join(output_lines)
        self.assertIn("No sessions found", output)


class ConfirmCleanTests(unittest.TestCase):
    def test_confirm_clean_returns_true_on_yes(self) -> None:
        ui = ConsoleUI(input_fn=lambda _prompt: "y")
        self.assertTrue(ui.confirm_clean(3))

    def test_confirm_clean_returns_true_on_yes_case_insensitive(self) -> None:
        ui = ConsoleUI(input_fn=lambda _prompt: "YES")
        self.assertTrue(ui.confirm_clean(3))

    def test_confirm_clean_returns_false_on_no(self) -> None:
        ui = ConsoleUI(input_fn=lambda _prompt: "n")
        self.assertFalse(ui.confirm_clean(3))

    def test_confirm_clean_returns_false_on_empty(self) -> None:
        ui = ConsoleUI(input_fn=lambda _prompt: "")
        self.assertFalse(ui.confirm_clean(3))

    def test_confirm_clean_includes_count_in_prompt(self) -> None:
        prompts: list[str] = []
        ui = ConsoleUI(input_fn=lambda prompt: prompts.append(prompt) or "n")
        ui.confirm_clean(5)

        self.assertEqual(1, len(prompts))
        self.assertIn("5", prompts[0])
        self.assertIn("session(s)", prompts[0])


class ResumeCommandTests(unittest.TestCase):
    def test_resume_command_uses_session_id_not_full_path(self) -> None:
        service = InterruptionService()
        feature_dir = Path(
            "/home/user/project/.agentmux/.sessions/20260101-120000-demo"
        )

        result = service._resume_command(feature_dir)

        self.assertIn("20260101-120000-demo", result)
        self.assertNotIn("/home/user/project", result)


class GoodbyeScreenTests(unittest.TestCase):
    def test_goodbye_canceled_shows_session_label(self) -> None:
        output_lines: list[str] = []

        with patch("agentmux.terminal_ui.screens._clear_screen"):
            goodbye_canceled(
                feature_name="demo",
                session_id="20260101-120000-demo",
                resume_command="agentmux resume 20260101-120000-demo",
                console=Mock(print=output_lines.append),
            )

        output = "\n".join(str(line) for line in output_lines)
        self.assertIn("Session:", output)
        self.assertIn("20260101-120000-demo", output)
        self.assertNotIn("Feature directory:", output)

    def test_goodbye_error_shows_session_label(self) -> None:
        output_lines: list[str] = []

        with patch("agentmux.terminal_ui.screens._clear_screen"):
            goodbye_error(
                feature_name="demo",
                session_id="20260101-120000-demo",
                error_reason="test error",
                resume_command="agentmux resume 20260101-120000-demo",
                console=Mock(print=output_lines.append),
            )

        output = "\n".join(str(line) for line in output_lines)
        self.assertIn("Session:", output)
        self.assertIn("20260101-120000-demo", output)
        self.assertNotIn("Feature directory:", output)


class CleanupFeatureDirTests(unittest.TestCase):
    def test_cleanup_prints_session_id_not_full_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / ".agentmux" / ".sessions" / "20260101-120000-demo"
            feature_dir.mkdir(parents=True)
            (feature_dir / "state.json").write_text("{}", encoding="utf-8")

            output_lines: list[str] = []
            with patch("builtins.print", output_lines.append):
                cleanup_feature_dir(feature_dir)

            output = "\n".join(output_lines)
            self.assertIn("20260101-120000-demo", output)
            self.assertNotIn(str(feature_dir.parent), output)


class SubcommandRoutingTests(unittest.TestCase):
    def test_main_routes_sessions_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            with (
                patch("os.getcwd", return_value=str(project_dir)),
                patch(
                    "agentmux.pipeline.PipelineApplication.run_sessions",
                    return_value=0,
                ) as mock_run,
            ):
                with patch("sys.argv", ["agentmux", "sessions"]):
                    result = pipeline.main()
                self.assertEqual(0, result)
                mock_run.assert_called_once()

    def test_main_routes_clean_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            with (
                patch("os.getcwd", return_value=str(project_dir)),
                patch(
                    "agentmux.pipeline.PipelineApplication.run_clean",
                    return_value=0,
                ) as mock_run,
            ):
                with patch("sys.argv", ["agentmux", "clean"]):
                    result = pipeline.main()
                self.assertEqual(0, result)
                mock_run.assert_called_once_with(force=False)

    def test_main_routes_clean_subcommand_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            with (
                patch("os.getcwd", return_value=str(project_dir)),
                patch(
                    "agentmux.pipeline.PipelineApplication.run_clean",
                    return_value=0,
                ) as mock_run,
            ):
                with patch("sys.argv", ["agentmux", "clean", "--force"]):
                    result = pipeline.main()
                self.assertEqual(0, result)
                mock_run.assert_called_once_with(force=True)


class RunSessionsTests(unittest.TestCase):
    def test_run_sessions_prints_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)

            session1 = app.sessions.root_dir() / "20260101-100000-session1"
            session1.mkdir(parents=True)
            write_state(session1 / "state.json", {"phase": "planning"})

            output_lines: list[str] = []
            with (
                patch.object(app.ui, "print", output_lines.append),
                patch(
                    "agentmux.pipeline.application.list_agentmux_sessions",
                    return_value=[],
                ),
            ):
                result = app.run_sessions()

            self.assertEqual(0, result)
            output = "\n".join(str(line) for line in output_lines)
            self.assertIn("20260101-100000-session1", output)


class RunCleanTests(unittest.TestCase):
    def test_run_clean_no_sessions_prints_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)

            output_lines: list[str] = []
            with patch.object(app.ui, "print", output_lines.append):
                result = app.run_clean(force=False)

            self.assertEqual(0, result)
            output = "\n".join(str(line) for line in output_lines)
            self.assertIn("No sessions to remove", output)

    def test_run_clean_with_force_skips_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)

            session1 = app.sessions.root_dir() / "20260101-100000-session1"
            session1.mkdir(parents=True)
            write_state(session1 / "state.json", {"phase": "planning"})

            output_lines: list[str] = []
            with (
                patch.object(app.ui, "print", output_lines.append),
                patch.object(
                    app.sessions,
                    "remove_all_sessions",
                    return_value=1,
                ) as mock_remove,
            ):
                result = app.run_clean(force=True)

            self.assertEqual(0, result)
            mock_remove.assert_called_once()

    def test_run_clean_without_force_prompts_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)

            session1 = app.sessions.root_dir() / "20260101-100000-session1"
            session1.mkdir(parents=True)
            write_state(session1 / "state.json", {"phase": "planning"})

            with (
                patch.object(
                    app.ui,
                    "confirm_clean",
                    return_value=False,
                ) as mock_confirm,
                patch.object(app.ui, "print"),
            ):
                result = app.run_clean(force=False)

            self.assertEqual(0, result)
            mock_confirm.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
