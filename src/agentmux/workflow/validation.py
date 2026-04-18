"""Sequential validation commands: library API, JSON result, and pane CLI entry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from ..configuration import load_layered_config

TAIL_LINES: int = 50


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of running configured validation shell commands."""

    passed: bool
    failed_command: str
    exit_code: int
    tail_output: str
    full_output: str


def _tail_text(text: str, n: int) -> str:
    if not text or n <= 0:
        return ""
    lines = text.splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "\n".join(lines[-n:])


def run_validation(
    commands: Sequence[str],
    cwd: Path,
    *,
    tail_lines: int = TAIL_LINES,
) -> ValidationResult:
    """Run shell commands sequentially; stream to stdout and capture full output."""
    cwd = Path(cwd)
    if not commands:
        return ValidationResult(
            passed=True,
            failed_command="",
            exit_code=0,
            tail_output="",
            full_output="",
        )

    full_text = ""
    for cmd in commands:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        chunk: list[str] = []
        for line in proc.stdout:
            print(line, end="")
            chunk.append(line)
        proc.wait()
        full_text += "".join(chunk)
        code = proc.returncode if proc.returncode is not None else -1
        if code != 0:
            return ValidationResult(
                passed=False,
                failed_command=cmd,
                exit_code=int(code),
                tail_output=_tail_text(full_text, tail_lines),
                full_output=full_text,
            )

    return ValidationResult(
        passed=True,
        failed_command="",
        exit_code=0,
        tail_output="",
        full_output=full_text,
    )


def run_pane_cli(argv: list[str] | None = None) -> int:
    """Pane runner: load config, run validation, write JSON to ``--result-path``."""
    parser = argparse.ArgumentParser(
        prog="python -m agentmux.workflow.validation",
        description="Run configured validation commands and write a JSON result file.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        required=True,
        help="Project root (used to load layered config).",
    )
    parser.add_argument(
        "--result-path",
        type=Path,
        required=True,
        help="Path to write validation_result.json.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="Working directory for subprocesses (default: project-dir).",
    )
    args = parser.parse_args(argv)

    project_dir = args.project_dir.resolve()
    cwd = args.cwd.resolve() if args.cwd else project_dir

    try:
        loaded = load_layered_config(project_dir)
    except (OSError, ValueError) as exc:
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 1

    commands = loaded.workflow_settings.validation.commands
    result = run_validation(commands, cwd=cwd)
    out = args.result_path.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(asdict(result), indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(run_pane_cli())
