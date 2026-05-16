"""Tests for config error path hint on startup (Finding 2)."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.pipeline.application import PipelineApplication
from agentmux.terminal_ui.console import ConsoleUI


def _make_app(project_dir: Path) -> PipelineApplication:
    ui = ConsoleUI(stdout=io.StringIO(), input_fn=lambda _: "")
    return PipelineApplication(project_dir=project_dir, ui=ui)


def _invalid_config(project_dir: Path) -> Path:
    """Write a config with a legacy key that triggers validation error."""
    config_path = project_dir / ".agentmux" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("version: 2\ndefaults:\n  profile: max\n", encoding="utf-8")
    return config_path


class StartupConfigErrorTests(unittest.TestCase):
    def _run_and_capture_stderr(self, method_name: str, project_dir: Path) -> str:
        app = _make_app(project_dir)
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf), contextlib.suppress(SystemExit):
            getattr(app, method_name)("dummy prompt")
        return stderr_buf.getvalue()

    def test_run_prompt_emits_config_path_on_invalid_config(self) -> None:
        """run_prompt prints config file path to stderr on validation error."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = _invalid_config(project_dir)
            stderr = self._run_and_capture_stderr("run_prompt", project_dir)

        self.assertIn(str(config_path), stderr)

    def test_run_issue_emits_config_path_on_invalid_config(self) -> None:
        """run_issue prints config file path to stderr on validation error."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = _invalid_config(project_dir)
            app = _make_app(project_dir)
            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf), contextlib.suppress(SystemExit):
                app.run_issue("123")
            stderr = stderr_buf.getvalue()

        self.assertIn(str(config_path), stderr)

    def test_run_resume_emits_config_path_on_invalid_config(self) -> None:
        """run_resume prints config file path to stderr on validation error."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = _invalid_config(project_dir)
            app = _make_app(project_dir)
            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf), contextlib.suppress(SystemExit):
                app.run_resume()
            stderr = stderr_buf.getvalue()

        self.assertIn(str(config_path), stderr)

    def test_run_prompt_exits_1_on_invalid_config(self) -> None:
        """run_prompt raises SystemExit(1) on config validation error."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _invalid_config(project_dir)
            app = _make_app(project_dir)
            with (
                patch("sys.stderr", io.StringIO()),
                self.assertRaises(SystemExit) as ctx,
            ):
                app.run_prompt("dummy")
        self.assertEqual(1, ctx.exception.code)
