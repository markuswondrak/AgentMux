from __future__ import annotations

import argparse
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import agentmux.pipeline as pipeline
from agentmux.configuration import load_builtin_catalog
from agentmux.terminal_ui.screens import render_logo
from agentmux.pipeline.init_command import (
    detect_clis,
    generate_config,
    prompt_role_config,
    prompt_stubs,
    run_init,
    validate_config,
)


class _FakePrompt:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


class InitRequirementsTests(unittest.TestCase):
    def test_render_logo_matches_reference_geometry(self) -> None:
        class _CaptureConsole:
            def __init__(self) -> None:
                self.lines: list[str] = []

            def print(self, text: str, **_kwargs: object) -> None:
                self.lines.append(text)

        console = _CaptureConsole()
        render_logo(console)

        rendered = "\n".join(
            re.sub(
                r"\[/?(?:blue|bold cyan|bold bright_cyan|bold magenta|dim)\]", "", line
            )
            for line in console.lines
        )
        expected = "\n".join(
            [
                "╭──────────────────────────────────────────────╮",
                "│   █████╗  ██████╗ ███████╗███╗   ██╗████████╗│",
                "│  ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝│",
                "│  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   │",
                "│  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   │",
                "│  ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   │",
                "│  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   │",
                "├──────────────────────────────┬───────────────┤",
                "│ ███╗   ███╗██╗   ██╗██╗  ██╗ │   [ ]──┐      │",
                "│ ████╗ ████║██║   ██║╚██╗██╔╝ │        │      │",
                "│ ██╔████╔██║██║   ██║ ╚███╔╝  │ ──[ ]──◆──[ ] │",
                "│ ██║╚██╔╝██║██║   ██║ ██╔██╗  │        │      │",
                "│ ██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗ │   [ ]──┘      │",
                "│ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝ │               │",
                "╰──────────────────────────────┴───────────────╯",
            ]
        )

        self.assertEqual(expected, rendered)

    def test_pipeline_main_routes_init_subcommand_before_parse_args(self) -> None:
        with (
            patch("sys.argv", ["agentmux", "init", "--defaults"]),
            patch(
                "agentmux.pipeline.application.PipelineApplication.__init__",
                side_effect=AssertionError(
                    "PipelineApplication should not be constructed for init subcommand"
                ),
            ),
            patch(
                "agentmux.pipeline.init_command.run_init", return_value=0
            ) as run_init_mock,
        ):
            result = pipeline.main()

        self.assertEqual(0, result)
        run_init_mock.assert_called_once_with(defaults_mode=True)

    def test_detect_clis_uses_shutil_which_for_all_known_providers(self) -> None:
        lookup = {
            "claude": "/usr/bin/claude",
            "codex": "/usr/bin/codex",
            "gemini": None,
            "opencode": None,
        }
        with patch(
            "agentmux.pipeline.init_command.shutil.which",
            side_effect=lambda name: lookup.get(name),
        ):
            detected = detect_clis()

        self.assertEqual(
            {"claude": True, "codex": True, "gemini": False, "opencode": False},
            detected,
        )

    def test_generate_config_writes_minimal_version_only_when_no_overrides(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            target = generate_config({}, project_dir, console=None, defaults_mode=True)
            parsed = yaml.safe_load(target.read_text(encoding="utf-8"))

        self.assertEqual({"version": 2}, parsed)

    def test_prompt_role_config_returns_only_role_override_diffs(self) -> None:
        defaults = load_builtin_catalog()
        answers = iter(
            [
                "claude",
                "Customize roles",
                "default",
                "sonnet",  # architect model (matches default baseline)
                "default",
                "sonnet",  # product-manager model (matches default baseline)
                "default",
                "sonnet",  # reviewer model
                "default",
                "gpt-5.3-codex",  # coder model (different provider)
                "default",
                "sonnet",  # designer model
            ]
        )

        def fake_select(*_args, **_kwargs):
            return _FakePrompt(next(answers))

        def fake_text(*_args, **_kwargs):
            return _FakePrompt(next(answers))

        fake_questionary = SimpleNamespace(select=fake_select, text=fake_text)
        with patch("agentmux.pipeline.init_command.questionary", fake_questionary):
            overrides = prompt_role_config(["claude", "codex"], defaults)

        # coder has different provider in defaults, so it should appear
        self.assertEqual({"roles": {"coder": {"provider": "claude"}}}, overrides)

    def test_prompt_role_config_quick_setup_uses_default_provider_for_all_roles(
        self,
    ) -> None:
        defaults = load_builtin_catalog()
        answers = iter(
            [
                "claude",
                "Use default provider for all roles",
            ]
        )

        def fake_select(*_args, **_kwargs):
            return _FakePrompt(next(answers))

        fake_questionary = SimpleNamespace(select=fake_select)
        with patch("agentmux.pipeline.init_command.questionary", fake_questionary):
            overrides = prompt_role_config(["claude", "codex"], defaults)

        self.assertEqual({"roles": {"coder": {"provider": "claude"}}}, overrides)

    def test_prompt_stubs_excludes_existing_files_from_choices(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            existing = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("already here", encoding="utf-8")
            seen_choices: dict[str, list[str]] = {}

            def fake_checkbox(_message, choices, **_kwargs):
                seen_choices["labels"] = list(choices)
                return _FakePrompt(["reviewer"])

            fake_questionary = SimpleNamespace(
                checkbox=fake_checkbox,
                Choice=lambda value, checked=False: value,
            )
            with patch("agentmux.pipeline.init_command.questionary", fake_questionary):
                selected = prompt_stubs(project_dir)

        self.assertEqual(["reviewer"], selected)
        self.assertNotIn("coder", seen_choices["labels"])

    def test_run_init_defaults_creates_minimal_config_and_claude_template(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            with patch(
                "agentmux.pipeline.init_command.Path.cwd", return_value=project_dir
            ):
                exit_code = run_init(defaults_mode=True)

            config = yaml.safe_load(
                (project_dir / ".agentmux" / "config.yaml").read_text(encoding="utf-8")
            )
            claude = (project_dir / "CLAUDE.md").read_text(encoding="utf-8")

        self.assertEqual(0, exit_code)
        self.assertEqual({"version": 2}, config)
        self.assertIn("# ", claude)
        self.assertIn("Build Command", claude)
        self.assertIn("Test Command", claude)
        self.assertIn("Lint Command", claude)
        self.assertFalse((project_dir / ".agentmux" / "prompts" / "agents").exists())

    def test_run_init_defaults_overwrites_config_and_preserves_existing_claude(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "version: 2\nroles:\n  coder:\n    provider: wrong\n    model: wrong-model\n",
                encoding="utf-8",
            )
            claude_path = project_dir / "CLAUDE.md"
            claude_path.write_text("keep me", encoding="utf-8")

            with patch(
                "agentmux.pipeline.init_command.Path.cwd", return_value=project_dir
            ):
                exit_code = run_init(defaults_mode=True)

            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            claude_text = claude_path.read_text(encoding="utf-8")

        self.assertEqual(0, exit_code)
        self.assertEqual({"version": 2}, config)
        self.assertEqual("keep me", claude_text)

    def test_validate_config_loads_generated_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            (project_dir / ".agentmux").mkdir(parents=True, exist_ok=True)
            (project_dir / ".agentmux" / "config.yaml").write_text(
                "version: 2\n", encoding="utf-8"
            )

            self.assertTrue(validate_config(project_dir, console=None))

    def test_logo_md_matches_reference_banner(self) -> None:
        logo_path = Path(__file__).resolve().parents[1] / "logo.md"
        logo = logo_path.read_text(encoding="utf-8")
        expected = """```
 ╭──────────────────────────────────────────────╮
 │   █████╗  ██████╗ ███████╗███╗   ██╗████████╗│
 │  ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝│
 │  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   │
 │  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   │
 │  ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   │
 │  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   │
 ├──────────────────────────────┬───────────────┤
 │ ███╗   ███╗██╗   ██╗██╗  ██╗ │   [ ]──┐      │
 │ ████╗ ████║██║   ██║╚██╗██╔╝ │        │      │
 │ ██╔████╔██║██║   ██║ ╚███╔╝  │ ──[ ]──◆──[ ] │
 │ ██║╚██╔╝██║██║   ██║ ██╔██╗  │        │      │
 │ ██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗ │   [ ]──┘      │
 │ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝ │               │
 ╰──────────────────────────────┴───────────────╯
```
"""
        self.assertEqual(expected, logo)


if __name__ == "__main__":
    unittest.main()
