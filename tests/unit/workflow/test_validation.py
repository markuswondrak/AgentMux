"""Unit tests for workflow validation runner (no tmux)."""

from __future__ import annotations

import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from agentmux.workflow.validation import TAIL_LINES, ValidationResult, run_validation


class TestRunValidationEmpty:
    def test_empty_commands_passes(self, tmp_path: Path) -> None:
        result = run_validation((), cwd=tmp_path)
        assert result == ValidationResult(
            passed=True,
            failed_command="",
            exit_code=0,
            tail_output="",
            full_output="",
        )


class TestRunValidationSuccess:
    def test_single_command_success(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cmd = f"{sys.executable} -c \"print('ok')\""
        result = run_validation([cmd], cwd=tmp_path)
        assert result.passed is True
        assert result.failed_command == ""
        assert result.exit_code == 0
        assert result.tail_output == ""
        assert "ok" in result.full_output
        captured = capsys.readouterr()
        assert "ok" in captured.out

    def test_sequential_commands_all_succeed(self, tmp_path: Path) -> None:
        c1 = f"{sys.executable} -c \"print('a')\""
        c2 = f"{sys.executable} -c \"print('b')\""
        result = run_validation([c1, c2], cwd=tmp_path)
        assert result.passed is True
        assert "a" in result.full_output and "b" in result.full_output


class TestRunValidationFailure:
    def test_stops_on_first_nonzero_exit(self, tmp_path: Path) -> None:
        fail = f"{sys.executable} -c \"import sys; print('bad'); sys.exit(3)\""
        ok = f"{sys.executable} -c \"print('never')\""
        result = run_validation([fail, ok], cwd=tmp_path)
        assert result.passed is False
        assert result.failed_command == fail
        assert result.exit_code == 3
        assert "bad" in result.full_output
        assert "never" not in result.full_output

    def test_tail_truncates_to_last_n_lines(self, tmp_path: Path) -> None:
        script = tmp_path / "fail_many.py"
        lines = TAIL_LINES + 10
        script.write_text(
            "\n".join(["print('x')"] * lines + ["import sys", "sys.exit(1)"]),
            encoding="utf-8",
        )
        cmd = f"{sys.executable} {shlex.quote(str(script))}"
        result = run_validation([cmd], cwd=tmp_path, tail_lines=TAIL_LINES)
        assert result.passed is False
        tail_lines = result.tail_output.strip().splitlines()
        assert len(tail_lines) <= TAIL_LINES
        assert "x" in result.tail_output


class TestValidationResultJson:
    def test_matches_expected_schema_keys(self) -> None:
        r = ValidationResult(
            passed=False,
            failed_command="npm test",
            exit_code=1,
            tail_output="last",
            full_output="all",
        )
        data = asdict(r)
        text = json.dumps(data)
        parsed = json.loads(text)
        assert set(parsed.keys()) == {
            "passed",
            "failed_command",
            "exit_code",
            "tail_output",
            "full_output",
        }
