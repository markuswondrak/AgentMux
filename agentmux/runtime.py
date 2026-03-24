from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Protocol

from .models import AgentConfig
from .tmux import (
    _find_pane_by_title,
    create_agent_pane,
    kill_agent_pane,
    park_agent_pane,
    send_prompt,
    show_agent_pane,
    tmux_kill_session,
    tmux_new_session,
    tmux_pane_exists,
)

SNAPSHOT_VERSION = 1
LEGACY_PANES_FILE = "panes.json"


class AgentRuntime(Protocol):
    def send(self, role: str, prompt_file: Path) -> None:
        ...

    def send_many(self, role: str, prompt_files: list[Path]) -> None:
        ...

    def deactivate(self, role: str) -> None:
        ...

    def deactivate_many(self, roles: Iterable[str]) -> None:
        ...

    def kill_primary(self, role: str) -> None:
        ...

    def finish_many(self, role: str) -> None:
        ...

    def spawn_task(self, role: str, task_id: str, prompt_file: Path) -> None:
        ...

    def finish_task(self, role: str, task_id: str) -> None:
        ...

    def shutdown(self, keep_session: bool) -> None:
        ...


class TmuxAgentRuntime:
    def __init__(
        self,
        *,
        feature_dir: Path,
        session_name: str,
        agents: dict[str, AgentConfig],
        primary_panes: dict[str, str | None],
        parallel_panes: dict[str, dict[int | str, str]] | None = None,
    ) -> None:
        self.feature_dir = feature_dir
        self.session_name = session_name
        self.agents = agents
        self.primary_panes = primary_panes
        self.parallel_panes = parallel_panes or {}
        self._normalize_primary_panes()

    @classmethod
    def create(
        cls,
        *,
        feature_dir: Path,
        session_name: str,
        agents: dict[str, AgentConfig],
        config_path: Path | None,
        initial_role: str = "architect",
    ) -> "TmuxAgentRuntime":
        if initial_role not in agents:
            raise ValueError(f"Unknown initial role: {initial_role}")
        panes = tmux_new_session(
            session_name,
            agents,
            feature_dir,
            config_path,
            agents[initial_role].trust_snippet,
            initial_role,
        )
        runtime = cls(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
            primary_panes=panes,
        )
        runtime._persist_snapshot()
        return runtime

    @classmethod
    def attach(
        cls,
        *,
        feature_dir: Path,
        session_name: str,
        agents: dict[str, AgentConfig],
    ) -> "TmuxAgentRuntime":
        primary_panes, parallel_panes = cls._load_snapshot(feature_dir)
        runtime = cls(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
            primary_panes=primary_panes,
            parallel_panes=parallel_panes,
        )
        runtime._rehydrate()
        runtime._persist_snapshot()
        return runtime

    @staticmethod
    def _load_snapshot(
        feature_dir: Path,
    ) -> tuple[dict[str, str | None], dict[str, dict[int | str, str]]]:
        snapshot_path = feature_dir / "runtime_state.json"
        if snapshot_path.exists():
            raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
            primary = {
                str(key): value if value is None else str(value)
                for key, value in dict(raw.get("primary", {})).items()
            }
            parallel: dict[str, dict[int | str, str]] = {}
            for role, workers in dict(raw.get("parallel", {})).items():
                parsed: dict[int | str, str] = {}
                for worker_key, pane_id in dict(workers).items():
                    if pane_id is None:
                        continue
                    key: int | str = str(worker_key)
                    if str(worker_key).isdigit():
                        key = int(str(worker_key))
                    parsed[key] = str(pane_id)
                if parsed:
                    parallel[str(role)] = parsed
            return primary, parallel

        legacy_path = feature_dir / LEGACY_PANES_FILE
        if not legacy_path.exists():
            return {}, {}

        panes = json.loads(legacy_path.read_text(encoding="utf-8"))
        primary: dict[str, str | None] = {}
        parallel: dict[str, dict[int | str, str]] = {}
        for role, pane_id in panes.items():
            if role.startswith("coder_"):
                suffix = role.split("_", 1)[1]
                if suffix.isdigit() and pane_id:
                    parallel.setdefault("coder", {})[int(suffix)] = str(pane_id)
                continue
            primary[str(role)] = None if pane_id is None else str(pane_id)
        return primary, parallel

    def _normalize_primary_panes(self) -> None:
        self.primary_panes.setdefault("_control", None)
        self.primary_panes.setdefault("architect", None)
        for role in self.agents:
            if role != "architect":
                self.primary_panes.setdefault(role, None)

    def _persist_snapshot(self) -> None:
        target = self.feature_dir / "runtime_state.json"
        data = {
            "version": SNAPSHOT_VERSION,
            "primary": self.primary_panes,
            "parallel": {
                role: {
                    str(worker): pane_id
                    for worker, pane_id in sorted(workers.items(), key=lambda item: str(item[0]))
                }
                for role, workers in sorted(self.parallel_panes.items())
                if workers
            },
        }
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.rename(target)

    def _validate_pane_id(self, pane_id: str | None) -> str | None:
        if pane_id and tmux_pane_exists(pane_id):
            return pane_id
        return None

    def _rehydrate(self) -> None:
        for role, pane_id in list(self.primary_panes.items()):
            if role == "_control":
                self.primary_panes[role] = self._validate_pane_id(pane_id)
                continue
            validated = self._validate_pane_id(pane_id)
            if validated is not None:
                self.primary_panes[role] = validated
                continue
            self.primary_panes[role] = _find_pane_by_title(self.session_name, role)

        for role, workers in list(self.parallel_panes.items()):
            validated_workers: dict[int | str, str] = {}
            for worker, pane_id in workers.items():
                validated = self._validate_pane_id(pane_id)
                if validated is not None:
                    validated_workers[worker] = validated
            if validated_workers:
                self.parallel_panes[role] = validated_workers
            else:
                self.parallel_panes.pop(role, None)

    def _ensure_primary_pane(self, role: str) -> str | None:
        pane_id = self.primary_panes.get(role)
        if pane_id and tmux_pane_exists(pane_id):
            return pane_id
        if role not in self.agents:
            return None
        pane_id = create_agent_pane(
            self.session_name,
            role,
            self.agents,
            self.agents[role].trust_snippet,
        )
        park_agent_pane(pane_id, self.session_name)
        self.primary_panes[role] = pane_id
        self._persist_snapshot()
        return pane_id

    def send(self, role: str, prompt_file: Path) -> None:
        pane_id = self._ensure_primary_pane(role)
        if not pane_id:
            return
        send_prompt(pane_id, prompt_file, self.session_name)

    def send_many(self, role: str, prompt_files: list[Path]) -> None:
        if not prompt_files:
            return
        primary = self._ensure_primary_pane(role)
        if not primary:
            return

        workers: dict[int, str] = {}
        for idx, prompt_file in enumerate(prompt_files, start=1):
            if idx == 1:
                pane_id = primary
                show_agent_pane(pane_id, self.session_name, exclusive=True)
            else:
                pane_id = create_agent_pane(
                    self.session_name,
                    role,
                    self.agents,
                    self.agents[role].trust_snippet,
                )
                show_agent_pane(pane_id, self.session_name, exclusive=False)
            workers[idx] = pane_id
            send_prompt(pane_id, prompt_file)

        self.parallel_panes[role] = workers
        self._persist_snapshot()

    def deactivate(self, role: str) -> None:
        park_agent_pane(self.primary_panes.get(role), self.session_name)

    def deactivate_many(self, roles: Iterable[str]) -> None:
        for role in roles:
            self.deactivate(role)

    def kill_primary(self, role: str) -> None:
        kill_agent_pane(self.primary_panes.get(role), self.session_name)
        self.primary_panes[role] = None
        self._persist_snapshot()

    def finish_many(self, role: str) -> None:
        workers = self.parallel_panes.get(role, {})
        primary = self.primary_panes.get(role)
        for pane_id in workers.values():
            if pane_id != primary:
                kill_agent_pane(pane_id, self.session_name)
        if role in self.parallel_panes:
            self.parallel_panes.pop(role, None)
            self._persist_snapshot()

    def spawn_task(self, role: str, task_id: str, prompt_file: Path) -> None:
        if role not in self.agents:
            return
        pane_id = create_agent_pane(
            self.session_name,
            role,
            self.agents,
            self.agents[role].trust_snippet,
        )
        park_agent_pane(pane_id, self.session_name)
        send_prompt(pane_id, prompt_file)
        self.parallel_panes.setdefault(role, {})[task_id] = pane_id
        self._persist_snapshot()

    def finish_task(self, role: str, task_id: str) -> None:
        workers = self.parallel_panes.get(role, {})
        pane_id = workers.get(task_id)
        if pane_id:
            kill_agent_pane(pane_id, self.session_name)
        if task_id in workers:
            workers.pop(task_id, None)
        if not workers:
            self.parallel_panes.pop(role, None)
        self._persist_snapshot()

    def shutdown(self, keep_session: bool) -> None:
        if not keep_session:
            tmux_kill_session(self.session_name)
