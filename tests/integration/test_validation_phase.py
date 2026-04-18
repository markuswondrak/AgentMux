"""Integration tests for validation CLI and pane runner (no tmux).

Covers requirements: empty ``validation.commands`` vs configured commands,
JSON result for the tmux pane runner, and exit codes for ``agentmux validate``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agentmux.pipeline.cli import main as cli_main
from agentmux.workflow.validation import run_pane_cli


def _write_project_config(
    project: Path,
    *,
    validation_block: str | None = None,
) -> None:
    (project / ".agentmux").mkdir(parents=True, exist_ok=True)
    text = "version: 2\n"
    if validation_block is not None:
        text += validation_block
    (project / ".agentmux" / "config.yaml").write_text(text, encoding="utf-8")


def test_agentmux_validate_no_commands_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 3 / CLI: no commands → message on stderr, exit 2."""
    _write_project_config(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["agentmux", "validate"])
    assert cli_main() == 2


def test_agentmux_validate_success_exits_0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured commands all succeed → exit 0."""
    py = sys.executable
    block = f'validation:\n  commands:\n    - "{py} -c \\"print(\\\\\\"ok\\\\\\")\\""\n'
    _write_project_config(tmp_path, validation_block=block)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["agentmux", "validate"])
    assert cli_main() == 0


def test_agentmux_validate_failure_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First failing command → exit 1."""
    py = sys.executable
    block = f'validation:\n  commands:\n    - "{py} -c \\"import sys; sys.exit(3)\\""\n'
    _write_project_config(tmp_path, validation_block=block)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["agentmux", "validate"])
    assert cli_main() == 1


def test_validation_module_writes_result_json(
    tmp_path: Path,
) -> None:
    """Pane runner: same commands as config, writes validation_result schema."""
    py = sys.executable
    block = (
        f'validation:\n  commands:\n    - "{py} -c \\"print(\\\\\\"pane\\\\\\")\\""\n'
    )
    _write_project_config(tmp_path, validation_block=block)
    out = tmp_path / "out" / "validation_result.json"
    rc = run_pane_cli(
        [
            "--project-dir",
            str(tmp_path),
            "--result-path",
            str(out),
            "--cwd",
            str(tmp_path),
        ]
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["exit_code"] == 0
    assert data["failed_command"] == ""
    assert "pane" in data["full_output"]
    assert set(data) == {
        "passed",
        "failed_command",
        "exit_code",
        "tail_output",
        "full_output",
    }
