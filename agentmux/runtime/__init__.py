from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Protocol

from ..agent_labels import role_display_label
from ..shared.models import AgentConfig
from .tmux_control import (
    ContentZone,
    _find_pane_by_title,
    create_agent_pane,
    send_text,
    send_prompt,
    set_pane_identity,
    tmux_kill_session,
    tmux_new_session,
    tmux_pane_exists,
)

SNAPSHOT_VERSION = 2
LEGACY_PANES_FILE = "panes.json"


class AgentRuntime(Protocol):
    def send(self, role: str, prompt_file: Path, display_label: str | None = None) -> None:
        ...

    def send_many(self, role: str, prompt_specs: list["ParallelPromptSpec" | Path]) -> None:
        ...

    def deactivate(self, role: str) -> None:
        ...

    def deactivate_many(self, roles: Iterable[str]) -> None:
        ...

    def kill_primary(self, role: str) -> None:
        ...

    def finish_many(self, role: str) -> None:
        ...

    def notify(self, role: str, text: str) -> None:
        ...

    def spawn_task(self, role: str, task_id: str, prompt_file: Path) -> None:
        ...

    def hide_task(self, role: str, task_id: int | str) -> None:
        ...

    def finish_task(self, role: str, task_id: str) -> None:
        ...

    def shutdown(self, keep_session: bool) -> None:
        ...


@dataclass(frozen=True)
class RegisteredPaneRef:
    role: str
    pane_id: str
    scope: Literal["primary", "parallel"]
    task_id: int | str | None = None
    label: str = ""


@dataclass(frozen=True)
class ParallelPromptSpec:
    task_id: int | str
    prompt_file: Path
    display_label: str | None = None


class TmuxAgentRuntime:
    def __init__(
        self,
        *,
        feature_dir: Path,
        session_name: str,
        agents: dict[str, AgentConfig],
        primary_panes: dict[str, str | None],
        zone: ContentZone,
        parallel_panes: dict[str, dict[int | str, str]] | None = None,
    ) -> None:
        self.feature_dir = feature_dir
        self.session_name = session_name
        self.agents = agents
        self.primary_panes = primary_panes
        self._zone = zone
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
        panes, zone = tmux_new_session(
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
            zone=zone,
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
        primary_panes, parallel_panes, visible = cls._load_snapshot(feature_dir)
        runtime = cls(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
            primary_panes=primary_panes,
            zone=ContentZone(session_name, visible=visible),
            parallel_panes=parallel_panes,
        )
        runtime._rehydrate()
        runtime._zone.restore(runtime._all_known_panes())
        runtime._persist_snapshot()
        return runtime

    @staticmethod
    def _load_snapshot(
        feature_dir: Path,
    ) -> tuple[dict[str, str | None], dict[str, dict[int | str, str]], list[str]]:
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
            visible = [str(pane_id) for pane_id in list(raw.get("visible", [])) if pane_id]
            return primary, parallel, visible

        legacy_path = feature_dir / LEGACY_PANES_FILE
        if not legacy_path.exists():
            return {}, {}, []

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
        return primary, parallel, []

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
            "visible": self._zone.visible,
            "parallel": {
                role: {
                    str(worker): pane_id
                    for worker, pane_id in sorted(
                        workers.items(),
                        key=lambda item: str(item[0]),
                    )
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

    def _all_known_panes(self) -> list[str]:
        panes: list[str] = []
        for role, pane_id in self.primary_panes.items():
            if role != "_control" and pane_id:
                panes.append(pane_id)
        for workers in self.parallel_panes.values():
            for pane_id in workers.values():
                if pane_id:
                    panes.append(pane_id)
        return panes

    def _load_state(self) -> dict:
        state_path = self.feature_dir / "state.json"
        try:
            text = state_path.read_text(encoding="utf-8").strip()
        except OSError:
            return {}
        if not text:
            return {}
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _display_label_for_task(self, role: str, task_id: int | str | None) -> str:
        return role_display_label(self.feature_dir, role, task_id=task_id, state=self._load_state())

    def registered_panes(self) -> list[RegisteredPaneRef]:
        panes: list[RegisteredPaneRef] = []
        for role, pane_id in self.primary_panes.items():
            if role == "_control" or not pane_id:
                continue
            panes.append(
                RegisteredPaneRef(
                    role=role,
                    pane_id=pane_id,
                    scope="primary",
                    label=self._display_label_for_task(role, None),
                )
            )
        for role, workers in sorted(self.parallel_panes.items()):
            for task_id, pane_id in sorted(workers.items(), key=lambda item: str(item[0])):
                if not pane_id:
                    continue
                panes.append(
                    RegisteredPaneRef(
                        role=role,
                        pane_id=pane_id,
                        scope="parallel",
                        task_id=task_id,
                        label=self._display_label_for_task(role, task_id),
                    )
                )
        return panes

    def missing_registered_panes(self) -> list[RegisteredPaneRef]:
        return [pane for pane in self.registered_panes() if not tmux_pane_exists(pane.pane_id)]

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
        if pane_id:
            return None
        if role not in self.agents:
            return None
        pane_id = create_agent_pane(
            self.session_name,
            role,
            self.agents,
            self.agents[role].trust_snippet,
        )
        self.primary_panes[role] = pane_id
        self._persist_snapshot()
        return pane_id

    def send(self, role: str, prompt_file: Path, display_label: str | None = None) -> None:
        pane_id = self._ensure_primary_pane(role)
        if not pane_id:
            return
        set_pane_identity(
            pane_id,
            role=role,
            display_label=display_label or self._display_label_for_task(role, None),
        )
        self._zone.show(pane_id)
        send_prompt(pane_id, prompt_file)
        self._persist_snapshot()

    def send_many(self, role: str, prompt_specs: list[ParallelPromptSpec | Path]) -> None:
        if not prompt_specs:
            return
        primary = self._ensure_primary_pane(role)
        if not primary:
            return

        normalized_specs: list[ParallelPromptSpec] = []
        for index, spec in enumerate(prompt_specs, start=1):
            if isinstance(spec, ParallelPromptSpec):
                normalized_specs.append(spec)
            else:
                normalized_specs.append(ParallelPromptSpec(task_id=index, prompt_file=spec))

        workers: dict[int | str, str] = {}
        ordered_task_ids: list[int | str] = []
        for idx, spec in enumerate(normalized_specs, start=1):
            task_id = spec.task_id
            ordered_task_ids.append(task_id)
            display_label = spec.display_label or self._display_label_for_task(role, task_id)
            if idx == 1:
                pane_id = primary
                set_pane_identity(pane_id, role=role, display_label=display_label)
            else:
                pane_id = create_agent_pane(
                    self.session_name,
                    role,
                    self.agents,
                    self.agents[role].trust_snippet,
                    display_label=display_label,
                )
            workers[task_id] = pane_id

        self._zone.show_parallel([workers[task_id] for task_id in ordered_task_ids])
        for spec in normalized_specs:
            send_prompt(workers[spec.task_id], spec.prompt_file)

        self.parallel_panes[role] = workers
        self._persist_snapshot()

    def deactivate(self, role: str) -> None:
        workers = self.parallel_panes.get(role, {})
        if workers:
            for pane_id in dict.fromkeys(workers.values()):
                self._zone.hide(pane_id)
        else:
            pane_id = self.primary_panes.get(role)
            if pane_id:
                self._zone.hide(pane_id)
        self._persist_snapshot()

    def deactivate_many(self, roles: Iterable[str]) -> None:
        for role in roles:
            self.deactivate(role)

    def kill_primary(self, role: str) -> None:
        pane_id = self.primary_panes.get(role)
        if pane_id:
            self._zone.remove(pane_id)
        self.primary_panes[role] = None
        workers = self.parallel_panes.get(role)
        if workers:
            remaining = {
                worker: worker_pane
                for worker, worker_pane in workers.items()
                if worker_pane != pane_id
            }
            if remaining:
                self.parallel_panes[role] = remaining
            else:
                self.parallel_panes.pop(role, None)
        self._persist_snapshot()

    def finish_many(self, role: str) -> None:
        workers = self.parallel_panes.get(role, {})
        primary = self.primary_panes.get(role)
        for pane_id in dict.fromkeys(workers.values()):
            if pane_id != primary:
                self._zone.remove(pane_id)
        if role in self.parallel_panes:
            self.parallel_panes.pop(role, None)
            self._persist_snapshot()

    def notify(self, role: str, text: str) -> None:
        pane_id = self.primary_panes.get(role)
        if not pane_id or not tmux_pane_exists(pane_id):
            return
        self._zone.show(pane_id)
        send_text(pane_id, text)
        self._persist_snapshot()

    def spawn_task(self, role: str, task_id: str, prompt_file: Path) -> None:
        if role not in self.agents:
            return
        pane_id = create_agent_pane(
            self.session_name,
            role,
            self.agents,
            self.agents[role].trust_snippet,
            display_label=self._display_label_for_task(role, task_id),
        )
        send_prompt(pane_id, prompt_file)
        self.parallel_panes.setdefault(role, {})[task_id] = pane_id
        self._persist_snapshot()

    def hide_task(self, role: str, task_id: int | str) -> None:
        workers = self.parallel_panes.get(role, {})
        pane_id = workers.get(task_id)
        if not pane_id or len(workers) <= 1:
            return
        self._zone.hide(pane_id)
        self._persist_snapshot()

    def finish_task(self, role: str, task_id: str) -> None:
        workers = self.parallel_panes.get(role, {})
        pane_id = workers.get(task_id)
        if pane_id:
            self._zone.remove(pane_id)
        if task_id in workers:
            workers.pop(task_id, None)
        if not workers:
            self.parallel_panes.pop(role, None)
        self._persist_snapshot()

    def shutdown(self, keep_session: bool) -> None:
        if not keep_session:
            tmux_kill_session(self.session_name)


class TmuxRuntimeFactory:
    def create(
        self,
        *,
        feature_dir: Path,
        session_name: str,
        agents: dict[str, AgentConfig],
        config_path: Path | None,
        initial_role: str = "architect",
    ) -> TmuxAgentRuntime:
        return TmuxAgentRuntime.create(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
            config_path=config_path,
            initial_role=initial_role,
        )

    def attach(
        self,
        *,
        feature_dir: Path,
        session_name: str,
        agents: dict[str, AgentConfig],
    ) -> TmuxAgentRuntime:
        return TmuxAgentRuntime.attach(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
        )
