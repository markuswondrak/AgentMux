#!/usr/bin/env python3
"""CLI command registry and argument parsing for agentmux."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import shtab

from ..configuration.providers import get_known_providers
from .application import PipelineApplication

DEFAULT_CONFIG_HINT = ".agentmux/config.yaml"


@dataclass
class Argument:
    """Represents a single argument for a command."""

    flags: tuple[str, ...]
    kwargs: dict[str, Any] = field(default_factory=dict)

    def __init__(self, flags: tuple[str, ...], **kwargs):
        self.flags = flags
        self.kwargs = kwargs


@dataclass
class Command:
    """Represents a CLI command with its arguments and handler."""

    name: str
    help: str
    handler: Callable[[argparse.Namespace, Path], int]
    arguments: list[Argument] = field(default_factory=list)


def handle_init(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the init command."""
    provider = getattr(args, "provider", None)
    if provider:
        from .init_command import run_init_provider

        return run_init_provider(
            provider, project_dir, defaults_mode=bool(getattr(args, "defaults", False))
        )
    from .init_command import run_init

    return run_init(defaults_mode=bool(getattr(args, "defaults", False)))


def handle_configure(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the configure command."""
    from .configure_command import run_configure

    return run_configure(
        provider=getattr(args, "provider", None),
        project_dir=project_dir,
        role=getattr(args, "role", None),
        model=getattr(args, "model", None),
        agent=getattr(args, "agent", None),
        force=bool(getattr(args, "force", False)),
        global_scope=bool(getattr(args, "global_scope", False)),
    )


def handle_sessions(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the sessions command."""
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    app = PipelineApplication(project_dir, config_path=config_path)
    return app.run_sessions()


def handle_clean(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the clean command."""
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    app = PipelineApplication(project_dir, config_path=config_path)
    return app.run_clean(force=bool(getattr(args, "force", False)))


def handle_completions(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the completions command - generate shell completion scripts."""
    parser = build_parser()
    completion_script = shtab.complete(parser, args.shell)
    print(completion_script)
    return 0


def handle_resume(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the resume command."""
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    app = PipelineApplication(project_dir, config_path=config_path)
    return app.run_resume(
        session=getattr(args, "session", None),
        keep_session=bool(getattr(args, "keep_session", False)),
    )


def handle_issue(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the issue command."""
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    app = PipelineApplication(project_dir, config_path=config_path)
    return app.run_issue(
        args.number_or_url,
        name=getattr(args, "name", None),
        keep_session=bool(getattr(args, "keep_session", False)),
        product_manager=bool(getattr(args, "product_manager", False)),
    )


def handle_validate(args: argparse.Namespace, project_dir: Path) -> int:
    """Run configured validation commands (same suite as the pipeline)."""
    from ..configuration import load_layered_config
    from ..workflow.validation import run_validation

    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    loaded = load_layered_config(project_dir, explicit_config_path=config_path)
    commands = loaded.workflow_settings.validation.commands
    if not commands:
        print("No validation commands configured.", file=sys.stderr)
        return 2
    result = run_validation(commands, cwd=project_dir)
    if result.passed:
        return 0
    return 1


def handle_run(args: argparse.Namespace, project_dir: Path) -> int:
    """Handle the default run command (prompt-based workflow)."""
    config_path = Path(args.config).resolve() if getattr(args, "config", None) else None
    app = PipelineApplication(project_dir, config_path=config_path)
    if args.orchestrate:
        return app.run_orchestrate(
            Path(args.orchestrate),
            keep_session=bool(getattr(args, "keep_session", False)),
        )
    return app.run_prompt(
        args.prompt,
        name=getattr(args, "name", None),
        keep_session=bool(getattr(args, "keep_session", False)),
        product_manager=bool(getattr(args, "product_manager", False)),
    )


# Command registry
COMMANDS: list[Command] = [
    Command(
        name="init",
        help="Initialize a new project with configuration scaffolding.",
        handler=handle_init,
        arguments=[
            Argument(
                ("provider",),
                nargs="?",
                help=f"Provider to set up ({', '.join(get_known_providers())}). "
                "When supplied, runs provider-specific setup only.",
            ),
            Argument(
                ("--defaults",),
                action="store_true",
                help="Run non-interactively with built-in defaults.",
            ),
        ],
    ),
    Command(
        name="configure",
        help="Configure provider, models, or agent entries for an existing project.",
        handler=handle_configure,
        arguments=[
            Argument(("provider",), nargs="?", help="Provider to configure."),
            Argument(("--role",), help="Role name for model update."),
            Argument(("--model",), help="Model string to set for the specified role."),
            Argument(
                ("--agent",), metavar="ROLE|all", help="Install opencode agent entry."
            ),
            Argument(
                ("--force",), action="store_true", help="Overwrite existing entries."
            ),
            Argument(
                ("--global",),
                dest="global_scope",
                action="store_true",
                help="Use global opencode.json scope.",
            ),
        ],
    ),
    Command(
        name="sessions",
        help="List all resumable sessions with phase, status, and timestamps.",
        handler=handle_sessions,
        arguments=[
            Argument(
                ("--config",),
                help="Optional config override path.",
            ),
        ],
    ),
    Command(
        name="clean",
        help="Remove all sessions and kill active tmux sessions.",
        handler=handle_clean,
        arguments=[
            Argument(
                ("--force",),
                action="store_true",
                help="Skip confirmation prompt.",
            ),
            Argument(
                ("--config",),
                help="Optional config override path.",
            ),
        ],
    ),
    Command(
        name="completions",
        help="Print shell completion script to stdout.",
        handler=handle_completions,
        arguments=[
            Argument(
                ("shell",),
                choices=["bash", "zsh"],
                help="Shell type for completion script.",
            ),
        ],
    ),
    Command(
        name="resume",
        help="Resume an interrupted pipeline session.",
        handler=handle_resume,
        arguments=[
            Argument(
                ("session",),
                nargs="?",
                help=(
                    "Feature directory or session name to resume. "
                    "If omitted, interactive selection is shown."
                ),
            ),
            Argument(
                ("--config",),
                help="Optional config override path.",
            ),
            Argument(
                ("--keep-session",),
                action="store_true",
                help="Keep the tmux session running after completion.",
            ),
        ],
    ),
    Command(
        name="validate",
        help=(
            "Run configured validation commands (tests, linting) "
            "for the current project."
        ),
        handler=handle_validate,
        arguments=[
            Argument(
                ("--config",),
                help="Optional config override path.",
            ),
        ],
    ),
    Command(
        name="issue",
        help="Bootstrap from a GitHub issue number or URL.",
        handler=handle_issue,
        arguments=[
            Argument(
                ("number_or_url",),
                help="GitHub issue number or URL to bootstrap requirements and slug.",
            ),
            Argument(
                ("--name",),
                help=(
                    "Optional feature slug. Defaults to timestamp plus a slug "
                    "derived from the issue."
                ),
            ),
            Argument(
                ("--config",),
                help="Optional config override path.",
            ),
            Argument(
                ("--keep-session",),
                action="store_true",
                help="Keep the tmux session running after completion.",
            ),
            Argument(
                ("--product-manager",),
                action="store_true",
                help="Enable product-management phase before planning.",
            ),
        ],
    ),
]


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="agentmux",
        description=(
            "Orchestrates a local tmux-based architect/coder/reviewer pipeline."
        ),
    )

    # Hidden --orchestrate flag for internal use
    parser.add_argument(
        "--orchestrate",
        help=argparse.SUPPRESS,
    )

    # Create subparsers
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Add registered commands
    for cmd in COMMANDS:
        cmd_parser = subparsers.add_parser(cmd.name, help=cmd.help)
        cmd_parser.set_defaults(handler=cmd.handler)

        for arg in cmd.arguments:
            cmd_parser.add_argument(*arg.flags, **arg.kwargs)

    # Add the default "run" subparser (for prompt-based workflow)
    run_parser = subparsers.add_parser(
        "run",
        help="Start a feature workflow with a prompt.",
    )
    run_parser.set_defaults(handler=handle_run)
    run_parser.add_argument(
        "prompt",
        nargs="?",
        help="Feature description as free text, or path to a .md file.",
    )
    run_parser.add_argument(
        "--name",
        help=(
            "Optional feature slug. Defaults to timestamp plus a slug "
            "derived from the prompt."
        ),
    )
    run_parser.add_argument(
        "--config",
        help=(
            "Optional config override. Without this flag the loader resolves "
            f"built-in defaults, ~/.config/agentmux/config.yaml, then "
            f"{DEFAULT_CONFIG_HINT} in the project."
        ),
    )
    run_parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Keep the tmux session running after completion.",
    )
    run_parser.add_argument(
        "--product-manager",
        action="store_true",
        help="Enable product-management phase before planning.",
    )

    return parser


def main() -> int:
    """Main entry point for the CLI."""
    # Get known subcommand names
    known_commands = {cmd.name for cmd in COMMANDS}
    known_commands.add("run")

    # Handle default subcommand injection
    # If first arg is not a known subcommand and doesn't start with '-', inject 'run'
    if (
        len(sys.argv) > 1
        and sys.argv[1] not in known_commands
        and not sys.argv[1].startswith("-")
    ):
        sys.argv.insert(1, "run")

    # Handle --orchestrate edge case (root-level hidden flag)
    # This preserves backward compatibility with the old CLI
    parser = build_parser()
    args = parser.parse_args()

    # Check if we have a handler
    if not hasattr(args, "handler"):
        parser.error("the following arguments are required: prompt")

    project_dir = Path.cwd().resolve()
    return args.handler(args, project_dir)


if __name__ == "__main__":
    sys.exit(main())
