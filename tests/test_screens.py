from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import agentmux.pipeline.application as application
from agentmux.sessions import PreparedSession
from agentmux.sessions.state_store import create_feature_files
from agentmux.terminal_ui.console import ConsoleUI
from agentmux.terminal_ui.screens import (
    goodbye_canceled,
    goodbye_error,
    goodbye_success,
    render_logo,
    welcome_screen,
)


def _strip_markup(text: str) -> str:
    return re.sub(r"\[/?[a-zA-Z][a-zA-Z0-9 _-]*\]", "", text)


class _CaptureConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **_kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    def rendered_text(self) -> str:
        return "\n".join(_strip_markup(line) for line in self.lines)


class ScreenRenderingTests(unittest.TestCase):
    def test_render_logo_outputs_banner(self) -> None:
        console = _CaptureConsole()
        render_logo(console=console)

        rendered = console.rendered_text()
        self.assertIn("█████╗  ██████╗ ███████╗", rendered)
        self.assertIn("╰──────────────────────────────┴───────────────╯", rendered)

    def test_welcome_screen_contains_feature_description_and_session_name(self) -> None:
        console = _CaptureConsole()
        welcome_screen(
            feature_description="Add welcome and goodbye screens.",
            session_name="agentmux-20260328-demo",
            console=console,
        )

        rendered = console.rendered_text()
        self.assertIn("Add welcome and goodbye screens.", rendered)
        self.assertIn("agentmux-20260328-demo", rendered)
        self.assertIn("Attaching to tmux session", rendered)

    def test_goodbye_success_contains_commit_pr_branch_elapsed_and_done(self) -> None:
        console = _CaptureConsole()
        goodbye_success(
            feature_name="add-welcome-and-goodbye-screen",
            commit_hash="abc1234",
            pr_url="https://github.com/acme/repo/pull/7",
            branch_name="feature/add-welcome-and-goodbye-screen",
            elapsed_seconds=3665,
            console=console,
        )

        rendered = console.rendered_text()
        self.assertIn("add-welcome-and-goodbye-screen", rendered)
        self.assertIn("abc1234", rendered)
        self.assertIn("https://github.com/acme/repo/pull/7", rendered)
        self.assertIn("feature/add-welcome-and-goodbye-screen", rendered)
        self.assertIn("1h 1m 5s", rendered)
        self.assertIn("Done.", rendered)

    def test_goodbye_success_omits_pr_line_when_pr_url_is_missing(self) -> None:
        console = _CaptureConsole()
        goodbye_success(
            feature_name="add-welcome-and-goodbye-screen",
            commit_hash="abc1234",
            pr_url=None,
            branch_name="feature/add-welcome-and-goodbye-screen",
            elapsed_seconds=5,
            console=console,
        )

        rendered = console.rendered_text()
        self.assertIn("abc1234", rendered)
        self.assertNotIn("PR:", rendered)

    def test_goodbye_canceled_contains_resume_command_and_feature_directory(self) -> None:
        console = _CaptureConsole()
        goodbye_canceled(
            feature_name="add-welcome-and-goodbye-screen",
            feature_dir="/tmp/.agentmux/.sessions/20260328-082756-add-welcome-and-goodbye-screen",
            resume_command="agentmux --resume 20260328-082756-add-welcome-and-goodbye-screen",
            console=console,
        )

        rendered = console.rendered_text()
        self.assertIn("Pipeline cancelled.", rendered)
        self.assertIn("agentmux --resume 20260328-082756-add-welcome-and-goodbye-screen", rendered)
        self.assertIn("/tmp/.agentmux/.sessions/20260328-082756-add-welcome-and-goodbye-screen", rendered)

    def test_goodbye_error_contains_failure_reason_and_feature_directory(self) -> None:
        console = _CaptureConsole()
        goodbye_error(
            feature_name="add-welcome-and-goodbye-screen",
            feature_dir="/tmp/.agentmux/.sessions/20260328-082756-add-welcome-and-goodbye-screen",
            error_reason="tmux attach failed with exit code 1",
            console=console,
        )

        rendered = console.rendered_text()
        self.assertIn("Pipeline failed.", rendered)
        self.assertIn("tmux attach failed with exit code 1", rendered)
        self.assertIn("/tmp/.agentmux/.sessions/20260328-082756-add-welcome-and-goodbye-screen", rendered)

    def test_screen_functions_fallback_to_plain_text_when_rich_is_unavailable(self) -> None:
        output = io.StringIO()
        with patch("agentmux.terminal_ui.screens.Console", None), patch("sys.stdout", output):
            welcome_screen("Ship welcome screen.", "agentmux-demo")
            goodbye_success("demo", "abc123", None, "feature/demo", 3)
            goodbye_canceled("demo", "/tmp/feature", "agentmux --resume demo")
            goodbye_error("demo", "/tmp/feature", "boom")

        rendered = output.getvalue()
        self.assertIn("Ship welcome screen.", rendered)
        self.assertIn("agentmux-demo", rendered)
        self.assertIn("Done.", rendered)
        self.assertIn("Pipeline cancelled.", rendered)
        self.assertIn("Pipeline failed.", rendered)
        self.assertNotIn("[bold", rendered)


class ApplicationScreenWiringTests(unittest.TestCase):
    def _make_prepared_session(self, project_dir: Path, prompt: str = "Ship welcome screen.\nExtra details.") -> PreparedSession:
        feature_dir = project_dir / ".agentmux" / ".sessions" / "20260328-082756-demo-feature"
        files = create_feature_files(
            project_dir=project_dir,
            feature_dir=feature_dir,
            prompt=prompt,
            session_name="agentmux-20260328-082756-demo-feature",
        )
        return PreparedSession(feature_dir=feature_dir, files=files, product_manager=False)

    def test_launch_attached_session_shows_startup_message_before_attach(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=messages.append))
            prepared = self._make_prepared_session(project_dir, prompt="First line summary.\nSecond line details.")
            args = SimpleNamespace(keep_session=False)

            with patch.object(app.runtime_factory, "create", return_value=object()), patch.object(
                app,
                "_start_background_orchestrator",
                return_value=None,
            ), patch(
                "agentmux.pipeline.application.subprocess.run",
                return_value=None,
            ), patch.object(
                app,
                "_post_attach_result",
                return_value=0,
            ):
                result = app._launch_attached_session(args, prepared, agents={}, session_name="agentmux-demo")

            self.assertEqual(0, result)
            self.assertTrue(any("starting up" in msg for msg in messages))

    def test_post_attach_result_success_reads_last_completion_summary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            prepared = self._make_prepared_session(project_dir)
            shutil.rmtree(prepared.feature_dir)
            completion_path = project_dir / ".agentmux" / ".last_completion.json"
            completion_path.parent.mkdir(parents=True, exist_ok=True)
            completion_path.write_text(
                json.dumps(
                    {
                        "feature_name": "demo-feature",
                        "commit_hash": "abc1234",
                        "pr_url": "https://github.com/acme/repo/pull/7",
                        "branch_name": "feature/demo-feature",
                    }
                ),
                encoding="utf-8",
            )

            with patch("agentmux.pipeline.application.goodbye_success") as goodbye_mock:
                result = app._post_attach_result(files=prepared.files, feature_dir=prepared.feature_dir, elapsed_seconds=95)

            self.assertEqual(0, result)
            self.assertEqual("demo-feature", goodbye_mock.call_args.args[0])
            self.assertEqual("abc1234", goodbye_mock.call_args.args[1])
            self.assertEqual("https://github.com/acme/repo/pull/7", goodbye_mock.call_args.args[2])
            self.assertEqual("feature/demo-feature", goodbye_mock.call_args.args[3])
            self.assertEqual(95, goodbye_mock.call_args.args[4])

    def test_post_attach_result_success_falls_back_when_completion_summary_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            prepared = self._make_prepared_session(project_dir)
            shutil.rmtree(prepared.feature_dir)

            with patch("agentmux.pipeline.application.goodbye_success") as goodbye_mock:
                result = app._post_attach_result(files=prepared.files, feature_dir=prepared.feature_dir, elapsed_seconds=12)

            self.assertEqual(0, result)
            self.assertEqual("demo-feature", goodbye_mock.call_args.args[0])
            self.assertEqual("", goodbye_mock.call_args.args[1])
            self.assertIsNone(goodbye_mock.call_args.args[2])
            self.assertEqual("", goodbye_mock.call_args.args[3])
            self.assertEqual(12, goodbye_mock.call_args.args[4])

    def test_launch_attached_session_renders_canceled_screen_on_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=lambda _message: None))
            prepared = self._make_prepared_session(project_dir)
            args = SimpleNamespace(keep_session=False)

            with patch.object(app.runtime_factory, "create", side_effect=KeyboardInterrupt), patch(
                "agentmux.pipeline.application.goodbye_canceled"
            ) as goodbye_mock:
                result = app._launch_attached_session(args, prepared, agents={}, session_name="agentmux-demo")

            self.assertEqual(130, result)
            self.assertEqual("demo-feature", goodbye_mock.call_args.args[0])
            self.assertEqual(str(prepared.feature_dir), goodbye_mock.call_args.args[1])
            self.assertIn("agentmux --resume", goodbye_mock.call_args.args[2])

    def test_launch_attached_session_renders_error_screen_on_subprocess_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=lambda _message: None))
            prepared = self._make_prepared_session(project_dir)
            args = SimpleNamespace(keep_session=False)

            with patch.object(app.runtime_factory, "create", return_value=object()), patch.object(
                app,
                "_start_background_orchestrator",
                return_value=None,
            ), patch(
                "agentmux.pipeline.application.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    returncode=1,
                    cmd=["tmux", "attach-session", "-t", "agentmux-demo"],
                    stderr="attach failed",
                ),
            ), patch("agentmux.pipeline.application.goodbye_error") as goodbye_mock:
                result = app._launch_attached_session(args, prepared, agents={}, session_name="agentmux-demo")

            self.assertEqual(1, result)
            self.assertEqual("demo-feature", goodbye_mock.call_args.args[0])
            self.assertEqual(str(prepared.feature_dir), goodbye_mock.call_args.args[1])
            self.assertIn("attach failed", goodbye_mock.call_args.args[2])

    def test_launch_attached_session_renders_error_screen_on_unexpected_exception(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=lambda _message: None))
            prepared = self._make_prepared_session(project_dir)
            args = SimpleNamespace(keep_session=False)

            with patch.object(app.runtime_factory, "create", side_effect=RuntimeError("boom")), patch(
                "agentmux.pipeline.application.goodbye_error"
            ) as goodbye_mock:
                result = app._launch_attached_session(args, prepared, agents={}, session_name="agentmux-demo")

            self.assertEqual(1, result)
            self.assertEqual("demo-feature", goodbye_mock.call_args.args[0])
            self.assertEqual(str(prepared.feature_dir), goodbye_mock.call_args.args[1])
            self.assertIn("boom", goodbye_mock.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
