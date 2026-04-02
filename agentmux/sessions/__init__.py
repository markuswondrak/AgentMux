from __future__ import annotations

import json
import os
import re
import shutil
import signal
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..shared.models import ProjectPaths, RuntimeFiles
from .state_store import (
    create_feature_files,
    infer_resume_phase,
    load_runtime_files,
    load_state,
    now_iso,
    write_state,
)


@dataclass(frozen=True)
class PromptInput:
    text: str
    slug_source: str


@dataclass(frozen=True)
class SessionRecord:
    feature_dir: Path
    state: dict[str, Any]


@dataclass(frozen=True)
class SessionCreateRequest:
    prompt: PromptInput
    session_name: str
    feature_name: str | None = None
    product_manager: bool = False
    gh_available: bool = False
    issue_number: str | None = None


@dataclass(frozen=True)
class PreparedSession:
    feature_dir: Path
    files: RuntimeFiles
    product_manager: bool


class SessionService:
    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir

    def root_dir(self) -> Path:
        paths = ProjectPaths.from_project(self.project_dir)
        return paths.sessions_root

    def list_resumable_sessions(self) -> list[SessionRecord]:
        root = self.root_dir()
        if not root.exists():
            return []

        sessions: list[SessionRecord] = []
        for candidate in root.iterdir():
            if not candidate.is_dir():
                continue
            state_path = candidate / "state.json"
            if not state_path.exists():
                continue
            sessions.append(SessionRecord(candidate, load_state(state_path)))

        return sorted(
            sessions,
            key=lambda item: str(item.state.get("updated_at", "")),
            reverse=True,
        )

    def resolve_resume_target(self, resume_arg: str) -> Path:
        resume_target = Path(str(resume_arg))
        if resume_target.is_absolute():
            return resume_target.resolve()

        in_session_root = self.root_dir() / resume_target
        if in_session_root.exists():
            return in_session_root.resolve()
        return (self.project_dir / resume_target).resolve()

    def prompt_input_from_value(self, prompt_value: str) -> PromptInput:
        prompt_path = Path(prompt_value)
        if prompt_value.endswith(".md") and prompt_path.is_file():
            return PromptInput(
                text=prompt_path.read_text(encoding="utf-8"),
                slug_source=prompt_path.stem,
            )
        return PromptInput(text=prompt_value, slug_source=prompt_value)

    def prepare_resumed_session(self, feature_dir: Path) -> PreparedSession:
        feature_dir = feature_dir.resolve()
        if not feature_dir.exists():
            raise SystemExit(f"Feature directory not found: {feature_dir}")

        state_path = feature_dir / "state.json"
        if not state_path.exists():
            raise SystemExit(f"No state.json found in {feature_dir}")

        # Kill any orphaned processes from previous session
        self._cleanup_orphaned_processes(feature_dir)

        files = load_runtime_files(self.project_dir, feature_dir)
        state = load_state(state_path)
        state["phase"] = infer_resume_phase(feature_dir, state)
        state["last_event"] = "resumed"
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        for key in (
            "interruption_category",
            "interruption_cause",
            "interruption_resume_command",
            "interruption_log_path",
        ):
            state.pop(key, None)
        write_state(state_path, state)
        return PreparedSession(
            feature_dir=feature_dir,
            files=files,
            product_manager=bool(state.get("product_manager")),
        )

    def _cleanup_orphaned_processes(self, feature_dir: Path) -> list[int]:
        """Kill any still-running tracked processes from a crashed session.

        Reads PIDs from runtime_state.json and kills them if still alive.
        Returns list of PIDs that were killed.
        """
        killed: list[int] = []
        snapshot_path = feature_dir / "runtime_state.json"

        if not snapshot_path.exists():
            return killed

        try:
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
            pids = raw.get("process_pids", {})
        except (json.JSONDecodeError, OSError):
            return killed

        for _pane_id, pid in pids.items():
            try:
                pid = int(pid)
                os.kill(pid, 0)  # Check if process exists

                # Process is still running, kill it
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(0.5)
                    os.kill(pid, 0)  # Check again
                    os.kill(pid, signal.SIGKILL)  # Force kill if still alive
                except ProcessLookupError:
                    pass  # Died from SIGTERM
                killed.append(pid)
            except (ProcessLookupError, PermissionError, ValueError):
                pass  # Already dead, can't access, or invalid PID

        return killed

    def create(self, request: SessionCreateRequest) -> PreparedSession:
        feature_name = request.feature_name or self._timestamped_feature_name(
            request.prompt.slug_source
        )
        feature_dir = self.root_dir() / feature_name
        files = create_feature_files(
            self.project_dir,
            feature_dir,
            request.prompt.text,
            request.session_name,
            product_manager=request.product_manager,
        )
        state = load_state(files.state)
        state["gh_available"] = bool(request.gh_available)
        if request.issue_number is not None:
            state["issue_number"] = request.issue_number
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(files.state, state)
        return PreparedSession(
            feature_dir=feature_dir,
            files=files,
            product_manager=bool(state.get("product_manager")),
        )

    def _timestamped_feature_name(self, slug_source: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{timestamp}-{slugify(slug_source)}"

    def remove_all_sessions(self, kill_tmux: bool = True) -> int:
        """Remove all session directories and optionally kill active tmux sessions.

        Returns the count of removed sessions.
        """
        # Lazy imports to avoid circular import issues
        from ..runtime.tmux_control import kill_agentmux_session, tmux_session_exists

        sessions = self.list_resumable_sessions()
        count = 0

        for session in sessions:
            feature_dir = session.feature_dir
            session_name = f"agentmux-{feature_dir.name}"

            if kill_tmux and tmux_session_exists(session_name):
                kill_agentmux_session(session_name)

            try:
                shutil.rmtree(feature_dir)
                count += 1
            except OSError:
                pass  # Directory might already be removed

        return count


def slugify(text: str, max_words: int = 8, max_length: int = 48) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = "-".join(words[:max_words]) or "feature"
    return slug[:max_length].strip("-") or "feature"
