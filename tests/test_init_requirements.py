from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import agentmux.pipeline as pipeline
from agentmux.configuration import load_builtin_catalog
from agentmux.pipeline.init_command import (
    detect_clis,
    generate_config,
    prompt_role_config,
    prompt_stubs,
    run_init,
    run_init_provider,
    validate_config,
)
from agentmux.terminal_ui.screens import render_logo


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
            "copilot": None,
            "qwen": None,
        }
        with patch(
            "agentmux.pipeline.init_command.shutil.which",
            side_effect=lambda name: lookup.get(name),
        ):
            detected = detect_clis()

        self.assertEqual(
            {
                "claude": True,
                "codex": True,
                "gemini": False,
                "opencode": False,
                "copilot": False,
                "qwen": False,
            },
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

        # coder model differs from baseline, so it should appear
        self.assertEqual({"roles": {"coder": {"model": "gpt-5.3-codex"}}}, overrides)

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

        self.assertEqual({}, overrides)

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
                (
                    "version: 2\nroles:\n  coder:\n"
                    "    provider: claude\n    model: sonnet\n"
                ),
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
        # Additive: existing roles are preserved when overrides are empty
        self.assertEqual(2, config["version"])
        self.assertEqual("claude", config["roles"]["coder"]["provider"])
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

    # =========================================================================
    # generate_config() — additive / no-overwrite-prompt tests
    # =========================================================================

    def test_generate_config_additive_no_write_when_identical(self) -> None:
        """Calling generate_config twice with same overrides does not change mtime."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            result = generate_config({}, project_dir, defaults_mode=True)
            first_mtime = result.stat().st_mtime

            # Call again with same overrides — should not write
            result2 = generate_config({}, project_dir, defaults_mode=True)
            second_mtime = result2.stat().st_mtime

            self.assertEqual(first_mtime, second_mtime)
            self.assertEqual(result, result2)

    def test_generate_config_writes_when_changed(self) -> None:
        """Calling with different overrides updates the file."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            generate_config(
                {"defaults": {"provider": "claude"}}, project_dir, defaults_mode=True
            )

            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual("claude", parsed["defaults"]["provider"])

    def test_generate_config_no_overwrite_prompt(self) -> None:
        """generate_config never calls _confirm."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("version: 2\n", encoding="utf-8")

            with patch(
                "agentmux.pipeline.init_command._confirm",
                side_effect=AssertionError("_confirm should not be called"),
            ):
                generate_config({}, project_dir, defaults_mode=False)

    def test_generate_config_merges_existing(self) -> None:
        """Existing file key not in overrides is preserved in output."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            config_path = project_dir / ".agentmux" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "version: 2\ngithub:\n  base_branch: develop\n",
                encoding="utf-8",
            )

            generate_config(
                {"defaults": {"provider": "claude"}},
                project_dir,
                defaults_mode=True,
            )

            parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual("develop", parsed["github"]["base_branch"])
            self.assertEqual("claude", parsed["defaults"]["provider"])

    # =========================================================================
    # prompt_role_config() — current_project_config tests
    # =========================================================================

    def test_prompt_role_config_current_project_defaults_provider(self) -> None:
        """current_project_config defaults.provider used as provider default."""
        defaults = load_builtin_catalog()
        current_project_config = {
            "defaults": {"provider": "codex"},
        }
        captured_defaults: dict[str, str] = {}

        def fake_select(message, choices, default=None, **_kwargs):
            if "Default provider" in message:
                captured_defaults["default"] = default
            return _FakePrompt(choices[0])

        fake_questionary = SimpleNamespace(select=fake_select)
        with patch("agentmux.pipeline.init_command.questionary", fake_questionary):
            prompt_role_config(
                ["claude", "codex"],
                defaults,
                current_project_config=current_project_config,
            )

        self.assertEqual("codex", captured_defaults.get("default"))

    def test_prompt_role_config_current_project_role_model(self) -> None:
        """current_project_config roles.coder.model used as default in model prompt."""
        defaults = load_builtin_catalog()
        current_project_config = {
            "defaults": {"provider": "claude"},
            "roles": {"coder": {"model": "gpt-5.3-codex"}},
        }
        captured_model_defaults: dict[str, str] = {}

        def fake_select(message, choices, default=None, **_kwargs):
            return _FakePrompt("Customize roles")

        def fake_text(message, default="", **_kwargs):
            if "coder" in message:
                captured_model_defaults["coder"] = default
            return _FakePrompt("")

        fake_questionary = SimpleNamespace(select=fake_select, text=fake_text)
        with patch("agentmux.pipeline.init_command.questionary", fake_questionary):
            prompt_role_config(
                ["claude"], defaults, current_project_config=current_project_config
            )

        self.assertEqual("gpt-5.3-codex", captured_model_defaults.get("coder"))

    def test_prompt_role_config_backward_compat(self) -> None:
        """Calling without current_project_config still works."""
        defaults = load_builtin_catalog()
        answers = iter(["claude", "Use default provider for all roles"])

        def fake_select(*_args, **_kwargs):
            return _FakePrompt(next(answers))

        fake_questionary = SimpleNamespace(select=fake_select)
        with patch("agentmux.pipeline.init_command.questionary", fake_questionary):
            overrides = prompt_role_config(["claude"], defaults)

        self.assertEqual({}, overrides)

    # =========================================================================
    # run_init_provider() tests
    # =========================================================================

    def test_run_init_provider_unknown_raises(self) -> None:
        """Unknown provider → SystemExit(1)."""
        with self.assertRaises(SystemExit) as ctx:
            run_init_provider("unknown_provider", Path("/tmp"))
        self.assertEqual(1, ctx.exception.code)

    def test_run_init_provider_copilot_noop(self) -> None:
        """copilot → returns 0, no MCP calls."""
        with patch("agentmux.pipeline.init_command.ensure_mcp_config") as mock_ensure:
            result = run_init_provider("copilot", Path("/tmp"))
            self.assertEqual(0, result)
            mock_ensure.assert_not_called()

    def test_run_init_provider_claude_home_level_mcp(self) -> None:
        """claude → ensure_mcp_config called with Path.home() as project_dir
        and a non-empty agents dict containing the provider."""
        with (
            patch("agentmux.pipeline.init_command.ensure_mcp_config") as mock_ensure,
            patch("agentmux.pipeline.init_command.Path.home") as mock_home,
        ):
            mock_home.return_value = Path("/fake/home")
            result = run_init_provider("claude", Path("/tmp/project"))

        self.assertEqual(0, result)
        mock_ensure.assert_called_once()
        call_args = mock_ensure.call_args[0]
        # agents dict (1st arg) must be non-empty and have provider="claude"
        agents = call_args[0]
        self.assertTrue(agents, "agents dict must not be empty")
        for agent_cfg in agents.values():
            self.assertEqual("claude", agent_cfg.provider)
        # project_dir is the 4th positional arg
        self.assertEqual(Path("/fake/home"), call_args[3])

    def test_run_init_provider_opencode_project_mcp(self) -> None:
        """opencode → ensure_mcp_config called with actual project_dir and
        non-empty agents dict containing provider="opencode"."""
        project_dir = Path("/tmp/project")
        with (
            patch("agentmux.pipeline.init_command.ensure_mcp_config") as mock_ensure,
            patch(
                "agentmux.pipeline.init_command.OpenCodeAgentConfigurator"
            ) as mock_ocac,
            patch(
                "agentmux.pipeline.init_command._select",
                return_value="project",
            ),
        ):
            mock_instance = mock_ocac.return_value
            mock_instance.install_all_agents.return_value = {}
            result = run_init_provider("opencode", project_dir)

        self.assertEqual(0, result)
        mock_ensure.assert_called_once()
        call_args = mock_ensure.call_args[0]
        agents = call_args[0]
        self.assertTrue(agents, "agents dict must not be empty")
        for agent_cfg in agents.values():
            self.assertEqual("opencode", agent_cfg.provider)
        self.assertEqual(project_dir, call_args[3])

    def test_run_init_provider_opencode_installs_agents(self) -> None:
        """opencode → OpenCodeAgentConfigurator.install_all_agents called."""
        project_dir = Path("/tmp/project")
        with (
            patch("agentmux.pipeline.init_command.ensure_mcp_config"),
            patch(
                "agentmux.pipeline.init_command.OpenCodeAgentConfigurator"
            ) as mock_ocac,
            patch(
                "agentmux.pipeline.init_command._select",
                return_value="project",
            ),
        ):
            mock_instance = mock_ocac.return_value
            mock_instance.install_all_agents.return_value = {
                "coder": "created",
                "architect": "created",
            }
            result = run_init_provider("opencode", project_dir)

        self.assertEqual(0, result)
        mock_instance.install_all_agents.assert_called_once()

    def test_run_init_provider_opencode_defaults_mode_project_scope(self) -> None:
        """defaults_mode=True → project scope used, no scope prompt."""
        project_dir = Path("/tmp/project")
        with (
            patch("agentmux.pipeline.init_command.ensure_mcp_config"),
            patch(
                "agentmux.pipeline.init_command.OpenCodeAgentConfigurator"
            ) as mock_ocac,
            patch(
                "agentmux.pipeline.init_command._select",
                side_effect=AssertionError(
                    "_select should not be called in defaults_mode"
                ),
            ),
        ):
            mock_instance = mock_ocac.return_value
            mock_instance.config_path.return_value = project_dir / "opencode.json"
            mock_instance.install_all_agents.return_value = {}
            result = run_init_provider("opencode", project_dir, defaults_mode=True)

        self.assertEqual(0, result)
        mock_instance.install_all_agents.assert_called_once()
        # Verify the path passed is project-scoped
        call_args = mock_instance.install_all_agents.call_args
        self.assertEqual(project_dir / "opencode.json", call_args[0][0])


if __name__ == "__main__":
    unittest.main()
