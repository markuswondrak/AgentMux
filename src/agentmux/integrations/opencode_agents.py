from __future__ import annotations

import json
from pathlib import Path

from ..shared.models import OPENCODE_AGENT_ROLES

OPENCODE_AGENT_PERSONAS: dict[str, tuple[str, str]] = {
    "architect": (
        "AgentMux architect role",
        "You are the architect agent for the agentmux pipeline. "
        "You create technical architecture and high-level design.",
    ),
    "planner": (
        "AgentMux planner role",
        "You are the planner agent for the agentmux pipeline. "
        "You break down architecture into actionable implementation plans.",
    ),
    "product-manager": (
        "AgentMux product manager role",
        "You are the product manager agent for the agentmux pipeline. "
        "You clarify business requirements and propose design direction.",
    ),
    "reviewer": (
        "AgentMux reviewer role",
        "You are the reviewer agent for the agentmux pipeline. "
        "You review implementations for correctness and quality.",
    ),
    "coder": (
        "AgentMux coder role",
        "You are the coder agent for the agentmux pipeline. "
        "You implement features as instructed by the orchestrator.",
    ),
    "designer": (
        "AgentMux designer role",
        "You are the designer agent for the agentmux pipeline. "
        "You create UI/UX designs and frontend specifications.",
    ),
    "code-researcher": (
        "AgentMux code researcher role",
        "You are the code researcher agent for the agentmux pipeline. "
        "You explore and analyze existing codebase structures.",
    ),
    "web-researcher": (
        "AgentMux web researcher role",
        "You are the web researcher agent for the agentmux pipeline. "
        "You search the internet for technical information.",
    ),
}


class OpenCodeAgentConfigurator:
    """Manages agent entries in opencode.json config files."""

    def config_path(self, project_dir: Path, global_scope: bool = False) -> Path:
        if global_scope:
            return Path.home() / ".config" / "opencode" / "opencode.json"
        return project_dir / "opencode.json"

    @staticmethod
    def _load_json(path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected object at top level in {path}")
        return data

    @staticmethod
    def _write_json(data: dict[str, object], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def has_agent(self, role: str, path: Path) -> bool:
        data = self._load_json(path)
        agents = data.get("agent", {})
        return isinstance(agents, dict) and f"agentmux-{role}" in agents

    def install_agent(self, role: str, path: Path, force: bool = False) -> str:
        data = self._load_json(path)
        agents = data.get("agent")
        if not isinstance(agents, dict):
            agents = {}

        key = f"agentmux-{role}"
        existing = key in agents

        if existing and not force:
            return "skipped"

        description, prompt = OPENCODE_AGENT_PERSONAS[role]
        agents[key] = {
            "description": description,
            "mode": "primary",
            "prompt": prompt,
        }
        data["agent"] = agents
        self._write_json(data, path)

        return "overwritten" if existing else "created"

    def install_all_agents(
        self,
        path: Path,
        roles: tuple[str, ...] = OPENCODE_AGENT_ROLES,
        force: bool = False,
    ) -> dict[str, str]:
        results: dict[str, str] = {}
        for role in roles:
            results[role] = self.install_agent(role, path, force=force)
        return results
