"""Native completion confirmation UI for agentmux.

Runs as a standalone tmux pane process:
    python -m agentmux.terminal_ui.completion_ui --feature-dir <path>

Displays the reviewer-authored implementation summary and asks the user
to approve (completing the pipeline) or request changes (restarting from
planning with the user's feedback text).

Writes one of:
    08_completion/approval.json  — on approval
    08_completion/changes.md     — on changes requested
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False


# ──────────────────────────────────────────────────────────────
# Colour palette (mirrors terminal_ui/colors.py — not imported
# here to keep this module self-contained as a subprocess entry)
# ──────────────────────────────────────────────────────────────
_PRIMARY = "bright_cyan"
_SECONDARY = "cyan"
_SUCCESS = "bold green"
_MUTED = "dim"
_BORDER = "blue"

_LOGO_LINES = [
    "[blue]╭──────────────────────────────────────────────╮[/blue]",
    f"[blue]│[/blue]   [bold {_PRIMARY}]█████╗  ██████╗ ███████╗███╗   ██╗████████╗[/bold {_PRIMARY}][blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue]  [bold {_PRIMARY}]██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/bold {_PRIMARY}][blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue]  [bold {_PRIMARY}]███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/bold {_PRIMARY}][blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue]  [bold {_PRIMARY}]██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/bold {_PRIMARY}][blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue]  [bold {_PRIMARY}]██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/bold {_PRIMARY}][blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue]  [bold {_PRIMARY}]╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/bold {_PRIMARY}][blue]│[/blue]",  # noqa: E501
    "[blue]├──────────────────────────────┬───────────────┤[/blue]",
    f"[blue]│[/blue] [bold {_SECONDARY}]███╗   ███╗██╗   ██╗██╗  ██╗ [/bold {_SECONDARY}][blue]│[/blue]   [dim][ ]──┐[/dim]      [blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue] [bold {_SECONDARY}]████╗ ████║██║   ██║╚██╗██╔╝ [/bold {_SECONDARY}][blue]│[/blue]        [dim]│[/dim]      [blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue] [bold {_SECONDARY}]██╔████╔██║██║   ██║ ╚███╔╝  [/bold {_SECONDARY}][blue]│[/blue] [dim]──[ ]──◆──[ ] [/dim][blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue] [bold {_SECONDARY}]██║╚██╔╝██║██║   ██║ ██╔██╗  [/bold {_SECONDARY}][blue]│[/blue]        [dim]│[/dim]      [blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue] [bold {_SECONDARY}]██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗ [/bold {_SECONDARY}][blue]│[/blue]   [dim][ ]──┘[/dim]      [blue]│[/blue]",  # noqa: E501
    f"[blue]│[/blue] [bold {_SECONDARY}]╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝ [/bold {_SECONDARY}][blue]│[/blue]               [blue]│[/blue]",  # noqa: E501
    "[blue]╰──────────────────────────────┴───────────────╯[/blue]",
]


def _git_changed_count(project_dir: Path) -> int:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return sum(1 for line in result.stdout.splitlines() if line.strip())
    except subprocess.CalledProcessError:
        return 0


def _read_summary(summary_path: Path) -> str:
    if not summary_path.exists():
        return "_No summary available._"
    return summary_path.read_text(encoding="utf-8").strip()


def _clear() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


# ──────────────────────────────────────────────────────────────
# Rich-based rendering
# ──────────────────────────────────────────────────────────────


def _render_screen(
    console: Console,
    summary: str,
    changed_count: int,
    feature_name: str,
) -> None:
    _clear()
    for line in _LOGO_LINES:
        console.print(line)
    console.print()
    console.print(
        Rule(
            f"[{_SUCCESS}]  ✓  IMPLEMENTATION COMPLETE  [/{_SUCCESS}]",
            style=_BORDER,
        )
    )
    console.print()

    summary_text = Text.from_markup(
        f"[bold]Feature:[/bold] {feature_name}\n"
        f"[bold]Changed files:[/bold] {changed_count}\n"
    )
    console.print(summary_text)
    console.print(Rule("[dim]Summary[/dim]", style=_MUTED))
    console.print()
    console.print(summary)
    console.print()
    console.print(
        Panel(
            f"[bold {_PRIMARY}]  \\[Y][/bold {_PRIMARY}]"
            "  Approve and complete the pipeline\n"
            "[bold yellow]  \\[N][/bold yellow]  Request changes",
            title="[bold]Confirmation[/bold]",
            border_style=_BORDER,
            padding=(0, 2),
        )
    )
    console.print()


def _render_screen_plain(
    summary: str,
    changed_count: int,
    feature_name: str,
) -> None:
    _clear()
    print("=" * 50)
    print("  AGENTMUX — IMPLEMENTATION COMPLETE")
    print("=" * 50)
    print(f"\nFeature:       {feature_name}")
    print(f"Changed files: {changed_count}\n")
    print("--- Summary ---")
    print(summary)
    print()
    print("[Y] Approve and complete the pipeline")
    print("[N] Request changes")
    print()


def _prompt_choice(console: Console | None) -> str:
    """Prompt for Y/N until a valid answer is given. Returns 'y' or 'n'."""
    while True:
        try:
            raw = input("Your choice [Y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit(1)
        if raw in ("y", "yes"):
            return "y"
        if raw in ("n", "no"):
            return "n"
        if console:
            console.print("[yellow]Please enter Y or N.[/yellow]")
        else:
            print("Please enter Y or N.")


def _prompt_changes(console: Console | None) -> str:
    """Ask the user to describe the changes they want. Returns the text."""
    if console:
        console.print()
        console.print(
            Panel(
                "[bold yellow]Describe the changes you'd like:[/bold yellow]",
                border_style="yellow",
                padding=(0, 2),
            )
        )
        console.print()
    else:
        print("\nDescribe the changes you'd like:\n")

    lines: list[str] = []
    if console:
        console.print(
            f"[{_MUTED}]"
            "(Enter your feedback below. Press Enter twice when done.)"
            f"[/{_MUTED}]"
        )
    else:
        print("(Enter your feedback below. Press Enter twice when done.)")
    print()

    blank_count = 0
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            break
        if line == "":
            blank_count += 1
            if blank_count >= 2:
                break
        else:
            blank_count = 0
        lines.append(line)

    # Remove trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────


def run(feature_dir: Path, project_dir: Path) -> None:
    completion_dir = feature_dir / "08_completion"
    completion_dir.mkdir(parents=True, exist_ok=True)

    # Infer feature name
    name = feature_dir.name
    match = re.match(r"^\d{8}-\d{6}-(.+)$", name)
    feature_name = match.group(1) if match else name

    summary = _read_summary(completion_dir / "summary.md")
    changed_count = _git_changed_count(project_dir)

    console: Console | None = None
    if _RICH_AVAILABLE and sys.stdout.isatty():
        console = Console()
        _render_screen(console, summary, changed_count, feature_name)
    else:
        _render_screen_plain(summary, changed_count, feature_name)

    choice = _prompt_choice(console)

    if choice == "y":
        approval_path = completion_dir / "approval.json"
        approval_path.write_text(
            json.dumps({"action": "approve", "exclude_files": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        if console:
            console.print()
            console.print(
                f"[{_SUCCESS}]✓ Approved. Completing pipeline...[/{_SUCCESS}]"
            )
        else:
            print("\n✓ Approved. Completing pipeline...")
    else:
        changes_text = _prompt_changes(console)
        changes_path = completion_dir / "changes.md"
        changes_path.write_text(changes_text + "\n", encoding="utf-8")
        if console:
            console.print()
            console.print(
                "[yellow]Changes requested. "
                "Restarting pipeline from planning...[/yellow]"
            )
        else:
            print("\nChanges requested. Restarting pipeline from planning...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agentmux native completion confirmation UI"
    )
    parser.add_argument(
        "--project-dir",
        required=True,
        type=Path,
        help="Absolute path to the project root directory.",
    )
    parser.add_argument(
        "--feature-dir",
        required=True,
        type=Path,
        help="Path to the feature session directory",
    )
    args = parser.parse_args()
    run(args.feature_dir, args.project_dir)


if __name__ == "__main__":
    main()
