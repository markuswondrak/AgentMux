from __future__ import annotations

import re
import textwrap
from typing import Any

from .colors import RICH_PRIMARY, RICH_SECONDARY

try:
    from rich.console import Console
except ImportError:  # pragma: no cover - optional at import time in this environment
    Console = None  # type: ignore[assignment]


_MARKUP_TAG_RE = re.compile(r"\[/?[a-zA-Z][a-zA-Z0-9 _-]*\]")


class _PlainConsole:
    def print(self, *objects: object, **_kwargs: object) -> None:
        text = " ".join(str(item) for item in objects)
        print(_MARKUP_TAG_RE.sub("", text))


def _console(console: Any | None) -> Any:
    if console is not None:
        return console
    if Console is None:
        return _PlainConsole()
    return Console()


def render_logo(console: Any | None = None) -> None:
    output = _console(console)
    output.print("[blue]╭──────────────────────────────────────────────╮[/blue]")
    output.print(
        f"[blue]│[/blue]   [bold {RICH_PRIMARY}]█████╗  ██████╗ ███████╗███╗   ██╗████████╗[/bold {RICH_PRIMARY}][blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue]  [bold {RICH_PRIMARY}]██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝[/bold {RICH_PRIMARY}][blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue]  [bold {RICH_PRIMARY}]███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   [/bold {RICH_PRIMARY}][blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue]  [bold {RICH_PRIMARY}]██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   [/bold {RICH_PRIMARY}][blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue]  [bold {RICH_PRIMARY}]██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   [/bold {RICH_PRIMARY}][blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue]  [bold {RICH_PRIMARY}]╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   [/bold {RICH_PRIMARY}][blue]│[/blue]"  # noqa: E501
    )
    output.print("[blue]├──────────────────────────────┬───────────────┤[/blue]")
    output.print(
        f"[blue]│[/blue] [bold {RICH_SECONDARY}]███╗   ███╗██╗   ██╗██╗  ██╗ [/bold {RICH_SECONDARY}][blue]│[/blue]   [dim][ ]──┐[/dim]      [blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue] [bold {RICH_SECONDARY}]████╗ ████║██║   ██║╚██╗██╔╝ [/bold {RICH_SECONDARY}][blue]│[/blue]        [dim]│[/dim]      [blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue] [bold {RICH_SECONDARY}]██╔████╔██║██║   ██║ ╚███╔╝  [/bold {RICH_SECONDARY}][blue]│[/blue] [dim]──[ ]──◆──[ ] [/dim][blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue] [bold {RICH_SECONDARY}]██║╚██╔╝██║██║   ██║ ██╔██╗  [/bold {RICH_SECONDARY}][blue]│[/blue]        [dim]│[/dim]      [blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue] [bold {RICH_SECONDARY}]██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗ [/bold {RICH_SECONDARY}][blue]│[/blue]   [dim][ ]──┘[/dim]      [blue]│[/blue]"  # noqa: E501
    )
    output.print(
        f"[blue]│[/blue] [bold {RICH_SECONDARY}]╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝ [/bold {RICH_SECONDARY}][blue]│[/blue]               [blue]│[/blue]"  # noqa: E501
    )
    output.print("[blue]╰──────────────────────────────┴───────────────╯[/blue]")


def _format_elapsed(elapsed_seconds: float) -> str:
    total_seconds = max(0, int(elapsed_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}h {minutes}m {seconds}s"


def _wrapped_lines(text: str, width: int = 76) -> list[str]:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []
    return textwrap.wrap(normalized, width=width) or [normalized]


def welcome_screen(
    feature_description: str, session_name: str, console: Any | None = None
) -> None:
    output = _console(console)
    render_logo(output)
    output.print(f"[bold {RICH_SECONDARY}]Welcome to AGENTMUX[/bold {RICH_SECONDARY}]")
    output.print("[bold]Feature:[/bold]")
    for line in _wrapped_lines(feature_description):
        output.print(f"  {line}")
    output.print(f"[bold]Session:[/bold] {session_name}")
    output.print("[dim]Attaching to tmux session...[/dim]")


def goodbye_success(
    feature_name: str,
    commit_hash: str,
    pr_url: str | None,
    branch_name: str,
    elapsed_seconds: float,
    console: Any | None = None,
) -> None:
    output = _console(console)
    render_logo(output)
    output.print("[bold green]Pipeline complete.[/bold green]")
    output.print(f"[bold]Feature:[/bold] {feature_name}")
    if commit_hash.strip():
        output.print(f"[bold]Commit:[/bold] {commit_hash}")
    if pr_url is not None and pr_url.strip():
        output.print(f"[bold]PR:[/bold] {pr_url}")
    if branch_name.strip():
        output.print(f"[bold]Branch:[/bold] {branch_name}")
    output.print(f"[bold]Elapsed:[/bold] {_format_elapsed(elapsed_seconds)}")
    output.print("[bold green]Done.[/bold green]")


def _clear_screen() -> None:
    import sys

    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


def goodbye_canceled(
    feature_name: str,
    session_id: str,
    resume_command: str,
    log_path: str | None = None,
    console: Any | None = None,
) -> None:
    _clear_screen()
    output = _console(console)
    render_logo(output)
    output.print("[bold yellow]Pipeline cancelled.[/bold yellow]")
    output.print("[yellow]Run canceled by user (Ctrl-C).[/yellow]")
    output.print(f"[bold]Feature:[/bold] {feature_name}")
    output.print(f"[bold]Session:[/bold] {session_id}")
    output.print(f"[bold]Resume:[/bold] [bold yellow]{resume_command}[/bold yellow]")
    if log_path:
        output.print(f"[dim]Diagnostics log: {log_path}[/dim]")


def goodbye_error(
    feature_name: str,
    session_id: str,
    error_reason: str,
    resume_command: str | None = None,
    log_path: str | None = None,
    console: Any | None = None,
) -> None:
    _clear_screen()
    output = _console(console)
    render_logo(output)
    output.print("[bold red]Pipeline failed.[/bold red]")
    output.print("[red]Run failed unexpectedly.[/red]")
    output.print(f"[bold]Feature:[/bold] {feature_name}")
    output.print(f"[bold]Reason:[/bold] {error_reason}")
    output.print(f"[bold]Session:[/bold] {session_id}")
    if resume_command:
        output.print(f"[bold]Resume:[/bold] [bold red]{resume_command}[/bold red]")
    if log_path:
        output.print(f"[dim]Diagnostics log: {log_path}[/dim]")
