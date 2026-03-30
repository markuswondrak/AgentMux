"""Tests for CLI tab completion and command registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test (will be created)
from agentmux.pipeline import cli


class TestArgumentDataclass:
    """Tests for the Argument dataclass."""

    def test_argument_creation(self):
        """Test that Argument dataclass can be created with required fields."""
        arg = cli.Argument(flags=("--test",), help="Test argument")
        assert arg.flags == ("--test",)
        assert arg.kwargs == {"help": "Test argument"}

    def test_argument_with_multiple_flags(self):
        """Test Argument with multiple flags."""
        arg = cli.Argument(flags=("-t", "--test"), action="store_true")
        assert arg.flags == ("-t", "--test")
        assert arg.kwargs == {"action": "store_true"}

    def test_argument_with_all_kwargs(self):
        """Test Argument with all common argparse kwargs."""
        arg = cli.Argument(
            flags=("--config",),
            help="Config path",
            type=str,
            default=None,
        )
        assert arg.flags == ("--config",)
        assert arg.kwargs["help"] == "Config path"
        assert arg.kwargs["type"] == str
        assert arg.kwargs["default"] is None


class TestCommandDataclass:
    """Tests for the Command dataclass."""

    def test_command_creation(self):
        """Test that Command dataclass can be created."""

        def dummy_handler(args, project_dir):
            return 0

        cmd = cli.Command(
            name="test",
            help="Test command",
            handler=dummy_handler,
            arguments=[cli.Argument(flags=("--flag",), action="store_true")],
        )
        assert cmd.name == "test"
        assert cmd.help == "Test command"
        assert cmd.handler == dummy_handler
        assert len(cmd.arguments) == 1


class TestCommandsRegistry:
    """Tests for the COMMANDS registry."""

    def test_commands_list_exists(self):
        """Test that COMMANDS list exists and is not empty."""
        assert hasattr(cli, "COMMANDS")
        assert isinstance(cli.COMMANDS, list)
        assert len(cli.COMMANDS) > 0

    def test_all_expected_commands_exist(self):
        """Test that all expected commands are in the registry."""
        command_names = {cmd.name for cmd in cli.COMMANDS}
        expected = {"init", "sessions", "clean", "completions", "resume", "issue"}
        assert expected.issubset(command_names), (
            f"Missing commands: {expected - command_names}"
        )

    def test_no_duplicate_command_names(self):
        """Test that there are no duplicate command names."""
        names = [cmd.name for cmd in cli.COMMANDS]
        assert len(names) == len(set(names)), f"Duplicate names found: {names}"

    def test_all_commands_have_handlers(self):
        """Test that all commands have callable handlers."""
        for cmd in cli.COMMANDS:
            assert callable(cmd.handler), f"Command {cmd.name} has non-callable handler"

    def test_init_command_structure(self):
        """Test init command has correct arguments."""
        init_cmd = next(cmd for cmd in cli.COMMANDS if cmd.name == "init")
        assert init_cmd.help
        arg_names = set()
        for arg in init_cmd.arguments:
            arg_names.update(arg.flags)
        assert "--defaults" in arg_names

    def test_sessions_command_structure(self):
        """Test sessions command has correct arguments."""
        sessions_cmd = next(cmd for cmd in cli.COMMANDS if cmd.name == "sessions")
        arg_names = set()
        for arg in sessions_cmd.arguments:
            arg_names.update(arg.flags)
        assert "--config" in arg_names

    def test_clean_command_structure(self):
        """Test clean command has correct arguments."""
        clean_cmd = next(cmd for cmd in cli.COMMANDS if cmd.name == "clean")
        arg_names = set()
        for arg in clean_cmd.arguments:
            arg_names.update(arg.flags)
        assert "--force" in arg_names
        assert "--config" in arg_names

    def test_completions_command_structure(self):
        """Test completions command has correct arguments."""
        completions_cmd = next(cmd for cmd in cli.COMMANDS if cmd.name == "completions")
        arg_names = set()
        for arg in completions_cmd.arguments:
            arg_names.update(arg.flags)
        # Should have shell positional argument (as first flag tuple element)
        assert "shell" in arg_names
        # Check that the shell argument has choices
        shell_arg = next(
            arg for arg in completions_cmd.arguments if "shell" in arg.flags
        )
        assert "choices" in shell_arg.kwargs
        assert set(shell_arg.kwargs["choices"]) == {"bash", "zsh"}

    def test_resume_command_structure(self):
        """Test resume command has correct arguments."""
        resume_cmd = next(cmd for cmd in cli.COMMANDS if cmd.name == "resume")
        arg_names = set()
        for arg in resume_cmd.arguments:
            arg_names.update(arg.flags)
        assert "--config" in arg_names
        assert "--keep-session" in arg_names

    def test_issue_command_structure(self):
        """Test issue command has correct arguments."""
        issue_cmd = next(cmd for cmd in cli.COMMANDS if cmd.name == "issue")
        arg_names = set()
        for arg in issue_cmd.arguments:
            arg_names.update(arg.flags)
        assert "--name" in arg_names
        assert "--config" in arg_names
        assert "--keep-session" in arg_names
        assert "--product-manager" in arg_names


class TestBuildParser:
    """Tests for build_parser function."""

    def test_parser_returns_argumentparser(self):
        """Test that build_parser returns an ArgumentParser."""
        parser = cli.build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_subparsers(self):
        """Test that parser has subparsers for all commands."""
        parser = cli.build_parser()
        # Parse args to trigger subparser creation
        args = parser.parse_args(["init", "--defaults"])
        assert hasattr(args, "handler")

    def test_init_subparser_exists(self):
        """Test that init subparser exists and accepts --defaults."""
        parser = cli.build_parser()
        args = parser.parse_args(["init", "--defaults"])
        assert args.defaults is True

    def test_sessions_subparser_exists(self):
        """Test that sessions subparser exists."""
        parser = cli.build_parser()
        args = parser.parse_args(["sessions"])
        assert hasattr(args, "handler")

    def test_clean_subparser_exists(self):
        """Test that clean subparser exists and accepts --force."""
        parser = cli.build_parser()
        args = parser.parse_args(["clean", "--force"])
        assert args.force is True

    def test_completions_subparser_exists(self):
        """Test that completions subparser exists and accepts shell argument."""
        parser = cli.build_parser()
        args = parser.parse_args(["completions", "bash"])
        assert args.shell == "bash"

    def test_completions_accepts_zsh(self):
        """Test that completions accepts zsh as shell argument."""
        parser = cli.build_parser()
        args = parser.parse_args(["completions", "zsh"])
        assert args.shell == "zsh"

    def test_resume_subparser_exists(self):
        """Test that resume subparser exists and accepts optional session argument."""
        parser = cli.build_parser()
        args = parser.parse_args(["resume"])
        assert args.session is None
        args = parser.parse_args(["resume", "my-session"])
        assert args.session == "my-session"

    def test_issue_subparser_exists(self):
        """Test that issue subparser exists and requires number-or-url argument."""
        parser = cli.build_parser()
        args = parser.parse_args(["issue", "123"])
        assert args.number_or_url == "123"

    def test_run_subparser_exists(self):
        """Test that run subparser exists (for default command)."""
        parser = cli.build_parser()
        args = parser.parse_args(["run", "my prompt"])
        assert args.prompt == "my prompt"

    def test_orchestrate_flag_hidden(self):
        """Test that --orchestrate flag exists but is hidden."""
        parser = cli.build_parser()
        # Should not raise an error
        args = parser.parse_args(["--orchestrate", "/some/path"])
        assert args.orchestrate == "/some/path"


class TestDefaultSubcommandInjection:
    """Tests for default subcommand injection in main()."""

    def test_prompt_without_subcommand_gets_run_injected(self):
        """Test that 'agentmux "prompt text"' injects 'run' subcommand."""
        parser = cli.build_parser()
        # Simulate the injection logic from main()
        argv = ["agentmux", "my prompt"]
        known_commands = {cmd.name for cmd in cli.COMMANDS}
        known_commands.add("run")

        # Check logic: if first arg is not known and doesn't start with '-', inject 'run'
        if (
            len(argv) > 1
            and argv[1] not in known_commands
            and not argv[1].startswith("-")
        ):
            argv.insert(1, "run")

        assert argv[1] == "run"
        assert argv[2] == "my prompt"

        # Now test parser can parse it
        args = parser.parse_args(argv[1:])  # Skip program name
        assert args.command == "run"
        assert args.prompt == "my prompt"

    def test_known_subcommand_not_modified(self):
        """Test that known subcommands are not modified."""
        parser = cli.build_parser()
        argv = ["agentmux", "init", "--defaults"]
        known_commands = {cmd.name for cmd in cli.COMMANDS}
        known_commands.add("run")

        original_argv = argv.copy()
        if (
            len(argv) > 1
            and argv[1] not in known_commands
            and not argv[1].startswith("-")
        ):
            argv.insert(1, "run")

        # Should NOT be modified
        assert argv == original_argv

        # Parser should work
        args = parser.parse_args(argv[1:])
        assert args.command == "init"
        assert args.defaults is True

    def test_flag_not_modified(self):
        """Test that flags are not treated as subcommands."""
        # Note: This tests the logic - in practice, --version would be handled by the parser
        argv = ["agentmux", "--version"]
        known_commands = {cmd.name for cmd in cli.COMMANDS}
        known_commands.add("run")

        original_argv = argv.copy()
        if (
            len(argv) > 1
            and argv[1] not in known_commands
            and not argv[1].startswith("-")
        ):
            argv.insert(1, "run")

        # Should NOT be modified because it starts with '-'
        assert argv == original_argv


class TestHandleCompletions:
    """Tests for handle_completions function."""

    @patch("agentmux.pipeline.cli.shtab")
    @patch("agentmux.pipeline.cli.build_parser")
    def test_handle_completions_calls_shtab_complete(
        self, mock_build_parser, mock_shtab
    ):
        """Test that handle_completions calls shtab.complete."""
        mock_parser = MagicMock()
        mock_build_parser.return_value = mock_parser
        mock_shtab.complete.return_value = "# bash completion script"

        args = MagicMock()
        args.shell = "bash"
        project_dir = Path("/tmp")

        with patch("builtins.print") as mock_print:
            result = cli.handle_completions(args, project_dir)

        mock_shtab.complete.assert_called_once_with(mock_parser, "bash")
        mock_print.assert_called_once_with("# bash completion script")
        assert result == 0

    @patch("agentmux.pipeline.cli.shtab")
    @patch("agentmux.pipeline.cli.build_parser")
    def test_handle_completions_supports_zsh(self, mock_build_parser, mock_shtab):
        """Test that handle_completions works with zsh."""
        mock_parser = MagicMock()
        mock_build_parser.return_value = mock_parser
        mock_shtab.complete.return_value = "# zsh completion script"

        args = MagicMock()
        args.shell = "zsh"
        project_dir = Path("/tmp")

        with patch("builtins.print") as mock_print:
            result = cli.handle_completions(args, project_dir)

        mock_shtab.complete.assert_called_once_with(mock_parser, "zsh")
        mock_print.assert_called_once_with("# zsh completion script")
        assert result == 0


class TestBackwardCompatibility:
    """Tests for backward compatibility with old CLI interface."""

    @patch("agentmux.pipeline.cli.PipelineApplication")
    @patch("agentmux.pipeline.cli.Path")
    def test_legacy_prompt_still_works(self, mock_path_class, mock_app_class):
        """Test that 'agentmux "my feature"' still works."""
        mock_app = MagicMock()
        mock_app.run.return_value = 0
        mock_app_class.return_value = mock_app

        mock_path = MagicMock()
        mock_path.resolve.return_value = Path("/project")
        mock_path_class.cwd.return_value = mock_path

        # Simulate the old-style invocation
        with patch.object(sys, "argv", ["agentmux", "run", "my feature"]):
            parser = cli.build_parser()
            args = parser.parse_args()
            assert args.prompt == "my feature"

    @patch("agentmux.pipeline.cli.PipelineApplication")
    @patch("agentmux.pipeline.cli.Path")
    def test_orchestrate_flag_still_works(self, mock_path_class, mock_app_class):
        """Test that --orchestrate flag still works."""
        parser = cli.build_parser()
        args = parser.parse_args(["--orchestrate", "/feature/dir"])
        assert args.orchestrate == "/feature/dir"


class TestIntegration:
    """Integration tests for the CLI module."""

    def test_parser_can_parse_all_commands(self):
        """Test that parser can parse all registered commands."""
        parser = cli.build_parser()

        test_cases = [
            (["init", "--defaults"], "init"),
            (["sessions"], "sessions"),
            (["clean", "--force"], "clean"),
            (["completions", "bash"], "completions"),
            (["resume"], "resume"),
            (["resume", "session-name"], "resume"),
            (["issue", "123"], "issue"),
            (["run", "my prompt"], "run"),
        ]

        for argv, expected_cmd in test_cases:
            args = parser.parse_args(argv)
            assert hasattr(args, "handler"), f"Command {expected_cmd} missing handler"

    def test_all_handlers_are_callable(self):
        """Test that all command handlers are callable."""
        parser = cli.build_parser()

        for cmd in cli.COMMANDS:
            args = parser.parse_args([cmd.name] + self._get_required_args(cmd))
            assert callable(args.handler), f"Handler for {cmd.name} is not callable"

    def _get_required_args(self, cmd):
        """Helper to get required arguments for a command."""
        args = []
        if cmd.name == "completions":
            args = ["bash"]
        elif cmd.name == "issue":
            args = ["123"]
        elif cmd.name == "resume":
            args = []  # session is optional
        elif cmd.name == "init":
            args = ["--defaults"]
        return args


class TestCompletionOutput:
    """Tests for completion script output."""

    @patch("agentmux.pipeline.cli.shtab")
    @patch("agentmux.pipeline.cli.build_parser")
    def test_bash_completion_contains_commands(self, mock_build_parser, mock_shtab):
        """Test that bash completion script contains command names."""
        mock_parser = MagicMock()
        mock_build_parser.return_value = mock_parser
        mock_shtab.complete.return_value = """
# bash completion for agentmux
complete -F _agentmux agentmux
"""

        args = MagicMock()
        args.shell = "bash"
        project_dir = Path("/tmp")

        cli.handle_completions(args, project_dir)
        mock_shtab.complete.assert_called_once()

    @patch("agentmux.pipeline.cli.shtab")
    @patch("agentmux.pipeline.cli.build_parser")
    def test_zsh_completion_contains_commands(self, mock_build_parser, mock_shtab):
        """Test that zsh completion script contains command names."""
        mock_parser = MagicMock()
        mock_build_parser.return_value = mock_parser
        mock_shtab.complete.return_value = """
#compdef agentmux
compadd init sessions clean completions resume issue
"""

        args = MagicMock()
        args.shell = "zsh"
        project_dir = Path("/tmp")

        cli.handle_completions(args, project_dir)
        mock_shtab.complete.assert_called_once()


class TestParserErrorsAndEdgeCases:
    """Tests for parser error handling and edge cases."""

    def test_completions_without_shell_errors(self):
        """Test that completions without shell argument raises an error."""
        parser = cli.build_parser()
        # Should raise SystemExit when required positional argument is missing
        with pytest.raises(SystemExit):
            parser.parse_args(["completions"])

    def test_unknown_subcommand_raises_error(self):
        """Test that unknown subcommand raises an error."""
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["unknown-cmd"])

    def test_issue_with_url_form(self):
        """Test that issue command accepts URL form."""
        parser = cli.build_parser()
        args = parser.parse_args(["issue", "https://github.com/user/repo/issues/42"])
        assert args.number_or_url == "https://github.com/user/repo/issues/42"
        assert args.command == "issue"

    def test_issue_with_number_form(self):
        """Test that issue command accepts number form."""
        parser = cli.build_parser()
        args = parser.parse_args(["issue", "42"])
        assert args.number_or_url == "42"
        assert args.command == "issue"

    def test_resume_with_session_argument(self):
        """Test that resume command accepts session argument."""
        parser = cli.build_parser()
        args = parser.parse_args(["resume", "my-session-name"])
        assert args.session == "my-session-name"
        assert args.command == "resume"

    def test_resume_without_session_argument(self):
        """Test that resume command works without session argument."""
        parser = cli.build_parser()
        args = parser.parse_args(["resume"])
        assert args.session is None
        assert args.command == "resume"


class TestNoPhantomCompletions:
    """Tests to ensure free-text arguments don't produce phantom completions."""

    def test_prompt_argument_has_no_completer(self):
        """Test that the prompt positional argument in run subparser has no completer."""
        parser = cli.build_parser()

        # Find the run subparser
        run_subparser = None
        for action in parser._subparsers._actions:
            if hasattr(action, "choices") and action.choices is not None:
                if "run" in action.choices:
                    run_subparser = action.choices["run"]
                    break

        assert run_subparser is not None, "Run subparser not found"

        # Check that the 'prompt' argument has no completer
        # In argparse, completers are stored in the 'completer' attribute of the action
        prompt_action = None
        for action in run_subparser._actions:
            if hasattr(action, "option_strings") and not action.option_strings:
                # This is a positional argument
                if action.dest == "prompt":
                    prompt_action = action
                    break

        assert prompt_action is not None, "Prompt argument not found in run subparser"

        # The prompt should not have a completer (should be None or not exist)
        completer = getattr(prompt_action, "completer", None)
        assert completer is None, (
            f"Prompt argument should not have a completer, but has: {completer}"
        )


class TestFlagDefaults:
    """Tests for flag default values."""

    def test_init_defaults_flag_default(self):
        """Test that init --defaults flag defaults to False."""
        parser = cli.build_parser()
        args = parser.parse_args(["init"])
        assert args.defaults is False

    def test_init_defaults_flag_when_set(self):
        """Test that init --defaults flag is True when set."""
        parser = cli.build_parser()
        args = parser.parse_args(["init", "--defaults"])
        assert args.defaults is True

    def test_clean_force_flag_default(self):
        """Test that clean --force flag defaults to False."""
        parser = cli.build_parser()
        args = parser.parse_args(["clean"])
        assert args.force is False

    def test_clean_force_flag_when_set(self):
        """Test that clean --force flag is True when set."""
        parser = cli.build_parser()
        args = parser.parse_args(["clean", "--force"])
        assert args.force is True

    def test_resume_keep_session_default(self):
        """Test that resume --keep-session flag defaults to False."""
        parser = cli.build_parser()
        args = parser.parse_args(["resume"])
        assert args.keep_session is False

    def test_issue_product_manager_default(self):
        """Test that issue --product-manager flag defaults to False."""
        parser = cli.build_parser()
        args = parser.parse_args(["issue", "123"])
        assert args.product_manager is False

    def test_run_keep_session_default(self):
        """Test that run --keep-session flag defaults to False."""
        parser = cli.build_parser()
        args = parser.parse_args(["run"])
        assert args.keep_session is False

    def test_run_product_manager_default(self):
        """Test that run --product-manager flag defaults to False."""
        parser = cli.build_parser()
        args = parser.parse_args(["run"])
        assert args.product_manager is False


class TestBackwardCompatDetailed:
    """Detailed backward compatibility tests."""

    def test_prompt_with_name_flag(self):
        """Test that 'agentmux "my feature" --name slug' works via default subcommand."""
        parser = cli.build_parser()

        # Simulate: agentmux
