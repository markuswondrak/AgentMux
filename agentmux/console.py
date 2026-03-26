from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from .sessions import SessionRecord


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
                f"{session.feature_dir.name} (phase: {session.state.get('phase', 'unknown')})"
            )
            return session.feature_dir

        self.print("Resumable sessions:")
        for index, session in enumerate(sessions, start=1):
            phase = session.state.get("phase", "unknown")
            last_event = session.state.get("last_event", "n/a")
            updated_at = str(session.state.get("updated_at", "n/a"))
            updated_label = updated_at[:16].replace("T", " ") if updated_at != "n/a" else "n/a"
            self.print(
                f"  {index}) {session.feature_dir.name:<36} "
                f"phase: {phase:<12} last_event: {last_event} (updated: {updated_label})"
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
