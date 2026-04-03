from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from ..sessions import SessionRecord


@dataclass
class ConsoleUI:
    input_fn: Callable[[str], str] = input
    output_fn: Callable[[str], None] = print
    stdin: TextIO = sys.stdin
    stdout: TextIO = sys.stdout

    def print(self, message: str) -> None:
        self.output_fn(message)

    def is_interactive(self) -> bool:
        return self.stdin.isatty()

    def select_session(self, sessions: list[SessionRecord]) -> Path:
        if not sessions:
            raise SystemExit("No resumable sessions found.")

        if len(sessions) == 1:
            session = sessions[0]
            self.print(
                "Auto-selected resumable session: "
                f"{session.feature_dir.name} "
                f"(phase: {session.state.get('phase', 'unknown')})"
            )
            return session.feature_dir

        self.print("Resumable sessions:")
        for index, session in enumerate(sessions, start=1):
            phase = session.state.get("phase", "unknown")
            last_event = session.state.get("last_event", "n/a")
            updated_at = str(session.state.get("updated_at", "n/a"))
            updated_label = (
                updated_at[:16].replace("T", " ") if updated_at != "n/a" else "n/a"
            )
            self.print(
                f"  {index}) {session.feature_dir.name:<36} "
                f"phase: {phase:<12} last_event: {last_event} "
                f"(updated: {updated_label})"
            )

        while True:
            choice = self.input_fn(f"Select session [1-{len(sessions)}]: ").strip()
            if not choice.isdigit():
                self.print("Invalid selection. Enter a number.")
                continue
            session_index = int(choice)
            if 1 <= session_index <= len(sessions):
                return sessions[session_index - 1].feature_dir
            self.print("Invalid selection. Try again.")

    def print_session_list(
        self, sessions: list[SessionRecord], active_tmux_sessions: list[str]
    ) -> None:
        """Print a tabular list of sessions with ID, phase, status,
        and updated timestamp."""
        if not sessions:
            self.print("No sessions found.")
            return

        # Header
        self.print(f"{'ID':<38} {'phase':<14} {'status':<10} {'updated'}")

        for session in sessions:
            session_id = session.feature_dir.name
            phase = session.state.get("phase", "unknown")
            updated_at = str(session.state.get("updated_at", "n/a"))
            updated_label = (
                updated_at[:16].replace("T", " ") if updated_at != "n/a" else "n/a"
            )

            # Check if session has an active tmux session
            tmux_name = f"agentmux-{session_id}"
            status = "running" if tmux_name in active_tmux_sessions else "stopped"

            self.print(f"{session_id:<38} {phase:<14} {status:<10} {updated_label}")

    def confirm_clean(self, session_count: int) -> bool:
        """Prompt user for confirmation before cleaning sessions.

        Returns True only if user enters 'y' or 'yes' (case-insensitive).
        """
        prompt = (
            f"Remove {session_count} session(s) and kill active tmux sessions? [y/N] "
        )
        response = self.input_fn(prompt).strip().lower()
        return response in ("y", "yes")
