#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .application import PipelineApplication

DEFAULT_CONFIG_HINT = ".agentmux/config.yaml"


def parse_init_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agentmux init")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Run non-interactively with built-in defaults.",
    )
    return parser.parse_args(argv)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orchestrates a local tmux-based architect/coder/reviewer pipeline.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Feature description as free text, or path to a .md file.",
    )
    parser.add_argument(
        "--name",
        help="Optional feature slug. Defaults to timestamp plus a slug derived from the prompt.",
    )
    parser.add_argument(
        "--config",
        help=(
            "Optional config override. Without this flag the loader resolves "
            f"built-in defaults, ~/.config/agentmux/config.yaml, then {DEFAULT_CONFIG_HINT} "
            "in the project."
        ),
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Keep the tmux session running after completion.",
    )
    parser.add_argument(
        "--product-manager",
        action="store_true",
        help="Enable product-management phase before planning.",
    )
    parser.add_argument(
        "--orchestrate",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const=True,
        default=None,
        help="Resume an interrupted pipeline session. Use with no value for interactive selection, or pass a feature dir/name.",
    )
    parser.add_argument(
        "--issue",
        help="GitHub issue number or URL to bootstrap requirements and slug.",
    )
    args = parser.parse_args()
    if not args.orchestrate and not args.prompt and not args.resume and not args.issue:
        parser.error("the following arguments are required: prompt")
    return args


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from .init_command import run_init

        init_args = parse_init_args(sys.argv[2:])
        return run_init(defaults_mode=bool(init_args.defaults))

    args = parse_args()
    config_path = Path(args.config).resolve() if args.config else None
    app = PipelineApplication(Path.cwd().resolve(), config_path=config_path)
    return app.run(args)


if __name__ == "__main__":
    sys.exit(main())
