"""Tests for terminal_ui/completion_ui.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agentmux.terminal_ui.completion_ui import (
    _LOGO_LINES,
    _prompt_changes,
    _prompt_choice,
    _read_summary,
    _render_screen_plain,
    run,
)

# ──────────────────────────────────────────────────────────────
# Logo tests
# ──────────────────────────────────────────────────────────────


def test_logo_has_no_mux_diagram_chars() -> None:
    """The confusing multiplexer diagram must be removed from the logo."""
    combined = "\n".join(_LOGO_LINES)
    assert "◆" not in combined, "MUX diamond '◆' still present in logo"
    assert "[ ]──" not in combined, "MUX node '[ ]──' still present in logo"


def test_logo_contains_checkmark_blocks() -> None:
    """The right panel should show the ASCII-art checkmark using block chars."""
    combined = "\n".join(_LOGO_LINES)
    assert "██" in combined, "Expected block characters '██' in logo checkmark"


def test_logo_checkmark_is_green() -> None:
    """The checkmark blocks should be rendered in green."""
    combined = "\n".join(_LOGO_LINES)
    assert "bold green" in combined, "Checkmark should use 'bold green' markup"


# ──────────────────────────────────────────────────────────────
# _read_summary
# ──────────────────────────────────────────────────────────────


def test_read_summary_missing_file(tmp_path: Path) -> None:
    result = _read_summary(tmp_path / "nonexistent.md")
    assert result == "_No summary available._"


def test_read_summary_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "summary.md"
    p.write_text("  Hello world  \n", encoding="utf-8")
    assert _read_summary(p) == "Hello world"


# ──────────────────────────────────────────────────────────────
# _prompt_choice — fallback (non-TTY plain text path)
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("user_input,expected", [("y", "y"), ("yes", "y"), ("Y", "y")])
def test_prompt_choice_fallback_yes(user_input: str, expected: str) -> None:
    with (
        patch("builtins.input", return_value=user_input),
        patch.object(sys.stdin, "isatty", return_value=False),
    ):
        result = _prompt_choice(None)
    assert result == expected


@pytest.mark.parametrize("user_input,expected", [("n", "n"), ("no", "n"), ("N", "n")])
def test_prompt_choice_fallback_no(user_input: str, expected: str) -> None:
    with (
        patch("builtins.input", return_value=user_input),
        patch.object(sys.stdin, "isatty", return_value=False),
    ):
        result = _prompt_choice(None)
    assert result == expected


def test_prompt_choice_fallback_reprompts_on_invalid() -> None:
    """Invalid input should reprompt; third call returns a valid answer."""
    call_count = 0

    def mock_input(_prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return "maybe"
        return "y"

    with (
        patch("builtins.input", side_effect=mock_input),
        patch.object(sys.stdin, "isatty", return_value=False),
    ):
        result = _prompt_choice(None)

    assert result == "y"
    assert call_count == 3


def test_prompt_choice_fallback_eof_exits() -> None:
    with (
        patch("builtins.input", side_effect=EOFError),
        patch.object(sys.stdin, "isatty", return_value=False),
        pytest.raises(SystemExit),
    ):
        _prompt_choice(None)


# ──────────────────────────────────────────────────────────────
# _prompt_changes
# ──────────────────────────────────────────────────────────────


def test_prompt_changes_single_line() -> None:
    inputs = iter(["Make it faster", "", ""])

    with patch("builtins.input", side_effect=lambda _="": next(inputs)):
        result = _prompt_changes(None)

    assert result == "Make it faster"


def test_prompt_changes_multiline_two_blanks_end() -> None:
    inputs = iter(["Line one", "Line two", "", ""])

    with patch("builtins.input", side_effect=lambda _="": next(inputs)):
        result = _prompt_changes(None)

    assert result == "Line one\nLine two"


def test_prompt_changes_eof_returns_partial() -> None:
    inputs = iter(["Some text"])

    def mock_input(_="") -> str:  # type: ignore[return]
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError from None

    with patch("builtins.input", side_effect=mock_input):
        result = _prompt_changes(None)

    assert result == "Some text"


# ──────────────────────────────────────────────────────────────
# _render_screen_plain
# ──────────────────────────────────────────────────────────────


def test_render_screen_plain_outputs_feature_name(  # noqa: E501
    capsys: pytest.CaptureFixture,
) -> None:
    with patch("agentmux.terminal_ui.completion_ui._clear"):
        _render_screen_plain("my-feature", 5, "my-feature")
    captured = capsys.readouterr()
    assert "my-feature" in captured.out
    assert "5" in captured.out


# ──────────────────────────────────────────────────────────────
# run() — writes approval.json on 'y'
# ──────────────────────────────────────────────────────────────


def test_run_writes_approval_json(tmp_path: Path) -> None:
    feature_dir = tmp_path / "20240101-120000-test-feature"
    feature_dir.mkdir()

    with (
        patch("agentmux.terminal_ui.completion_ui._RICH_AVAILABLE", False),
        patch("agentmux.terminal_ui.completion_ui._render_screen_plain"),
        patch("agentmux.terminal_ui.completion_ui._git_changed_count", return_value=3),
        patch("builtins.input", return_value="y"),
        patch.object(sys.stdin, "isatty", return_value=False),
    ):
        run(feature_dir, tmp_path)

    approval = feature_dir / "08_completion" / "approval.json"
    assert approval.exists()
    data = json.loads(approval.read_text())
    assert data["action"] == "approve"


def test_run_writes_changes_md(tmp_path: Path) -> None:
    feature_dir = tmp_path / "20240101-120000-test-feature"
    feature_dir.mkdir()

    inputs = iter(["n", "Please add tests", "", ""])

    def mock_input(_prompt: str = "") -> str:
        return next(inputs)

    with (
        patch("agentmux.terminal_ui.completion_ui._RICH_AVAILABLE", False),
        patch("agentmux.terminal_ui.completion_ui._render_screen_plain"),
        patch("agentmux.terminal_ui.completion_ui._git_changed_count", return_value=1),
        patch("builtins.input", side_effect=mock_input),
        patch.object(sys.stdin, "isatty", return_value=False),
    ):
        run(feature_dir, tmp_path)

    changes = feature_dir / "08_completion" / "changes.md"
    assert changes.exists()
    assert "Please add tests" in changes.read_text()
