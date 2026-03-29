#!/usr/bin/env python3
"""CLI entry point for agentmux pipeline."""

from __future__ import annotations

from .application import PipelineApplication
from .cli import DEFAULT_CONFIG_HINT, build_parser, main

__all__ = ["main", "DEFAULT_CONFIG_HINT", "PipelineApplication", "build_parser"]

# Re-export for backward compatibility
# The actual implementation has been moved to cli.py


def parse_init_args(argv: list):
    """Backward compatibility - init args are now handled by cli module."""
    import argparse

    parser = argparse.ArgumentParser(prog="agentmux init")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Run non-interactively with built-in defaults.",
    )
    return parser.parse_args(argv)


def parse_clean_args(argv: list):
    """Backward compatibility - clean args are now handled by cli module."""
    import argparse

    parser = argparse.ArgumentParser(prog="agentmux clean")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    return parser.parse_args(argv)


class _BackwardCompatibleNamespace:
    """Wrapper to provide backward compatibility for old-style args.

    Maps new subcommand structure to old attribute names:
    - resume subcommand -> args.resume (True or session name)
    - issue subcommand -> args.issue (issue value)
    - run subcommand -> args.prompt (prompt value)
    """

    def __init__(self, args):
        self._args = args
        self._command = getattr(args, "command", None)

    def __getattr__(self, name):
        # Map old attribute names to new structure
        if name == "resume":
            if self._command == "resume":
                # resume subcommand: session attribute becomes resume
                session = getattr(self._args, "session", None)
                return session if session else True
            return None
        elif name == "issue":
            if self._command == "issue":
                # issue subcommand: number_or_url attribute becomes issue
                return getattr(self._args, "number_or_url", None)
            return None
        elif name == "prompt":
            if self._command == "run":
                # run subcommand: prompt attribute
                return getattr(self._args, "prompt", None)
            return None
        elif name == "orchestrate":
            return getattr(self._args, "orchestrate", None)
        elif name == "name":
            return getattr(self._args, "name", None)
        elif name == "config":
            return getattr(self._args, "config", None)
        elif name == "keep_session":
            return getattr(self._args, "keep_session", False)
        elif name == "product_manager":
            return getattr(self._args, "product_manager", False)
        elif name == "defaults":
            return getattr(self._args, "defaults", False)
        elif name == "force":
            return getattr(self._args, "force", False)
        elif name == "shell":
            return getattr(self._args, "shell", None)
        elif name == "session":
            return getattr(self._args, "session", None)
        elif name == "number_or_url":
            return getattr(self._args, "number_or_url", None)
        elif name == "handler":
            return getattr(self._args, "handler", None)
        elif name == "command":
            return self._command

        # Fallback to underlying args
        return getattr(self._args, name, None)


def parse_args():
    """Backward compatibility - returns parsed args for the old-style main workflow.

    Note: This function is deprecated. Use build_parser() for new code.
    """
    import sys
    from .cli import build_parser as _build_parser

    # Save original argv for restoration
    original_argv = sys.argv.copy()

    try:
        # For backward compatibility, handle the old --resume and --issue flags
        # These have been moved to subcommands
        known_commands = {
            "init",
            "sessions",
            "clean",
            "completions",
            "resume",
            "issue",
            "run",
        }

        # Check if first arg after program is a known subcommand
        if len(sys.argv) > 1 and sys.argv[1] in known_commands:
            parser = _build_parser()
            args = parser.parse_args()
            return _BackwardCompatibleNamespace(args)

        # Check for old-style --resume or --issue flags and convert them
        if "--resume" in sys.argv:
            idx = sys.argv.index("--resume")
            sys.argv.pop(idx)  # Remove --resume
            sys.argv.insert(1, "resume")  # Add 'resume' subcommand
            # Check if there's a value that should be the session
            # If the next arg doesn't start with '-', it's the session value
            if idx < len(sys.argv) and not sys.argv[idx].startswith("-"):
                pass  # Session value is already in the right place
            parser = _build_parser()
            args = parser.parse_args()
            return _BackwardCompatibleNamespace(args)

        if "--issue" in sys.argv:
            idx = sys.argv.index("--issue")
            issue_value = sys.argv.pop(idx + 1)  # Get the issue value
            sys.argv.pop(idx)  # Remove --issue
            # Remove any prompt that was before --issue (old CLI allowed this)
            # The new issue subcommand doesn't take a prompt
            # Check if there's a bare argument at index 1 (the prompt)
            if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
                # This is a prompt argument from the old CLI, remove it
                sys.argv.pop(1)
            sys.argv.insert(1, "issue")  # Add 'issue' subcommand
            sys.argv.insert(2, issue_value)  # Add issue value
            parser = _build_parser()
            args = parser.parse_args()
            return _BackwardCompatibleNamespace(args)

        # For bare prompts (no subcommand, no flags), inject 'run' subcommand
        # similar to what main() does
        if (
            len(sys.argv) > 1
            and sys.argv[1] not in known_commands
            and not sys.argv[1].startswith("-")
        ):
            sys.argv.insert(1, "run")
            parser = _build_parser()
            args = parser.parse_args()
            return _BackwardCompatibleNamespace(args)

        # Default case: just parse normally
        parser = _build_parser()
        args = parser.parse_args()
        return _BackwardCompatibleNamespace(args)

    finally:
        # Restore original argv
        sys.argv = original_argv

    # Check for old-style --resume or --issue flags and convert them
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        sys.argv.pop(idx)  # Remove --resume
        sys.argv.insert(1, "resume")  # Add 'resume' subcommand
        # Check if there's a value that should be the session
        # If the next arg doesn't start with '-', it's the session value
        if idx < len(sys.argv) and not sys.argv[idx].startswith("-"):
            pass  # Session value is already in the right place
        parser = _build_parser()
        return parser.parse_args()

    if "--issue" in sys.argv:
        idx = sys.argv.index("--issue")
        issue_value = sys.argv.pop(idx + 1)  # Get the issue value
        sys.argv.pop(idx)  # Remove --issue
        sys.argv.insert(1, "issue")  # Add 'issue' subcommand
        sys.argv.insert(2, issue_value)  # Add issue value
        parser = _build_parser()
        return parser.parse_args()

    # For bare prompts (no subcommand, no flags), inject 'run' subcommand
    # similar to what main() does
    if (
        len(sys.argv) > 1
        and sys.argv[1] not in known_commands
        and not sys.argv[1].startswith("-")
    ):
        sys.argv.insert(1, "run")
        parser = _build_parser()
        return parser.parse_args()

    # Default case: just parse normally
    parser = _build_parser()
    return parser.parse_args()
