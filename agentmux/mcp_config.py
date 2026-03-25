from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
import json
import shutil
from pathlib import Path
from typing import Iterable

from .models import AgentConfig


@dataclass(frozen=True)
class McpServerSpec:
    """Provider-agnostic definition of an MCP server to inject."""

    name: str
    module: str
    env: dict[str, str]


class McpInjector(ABC):
    """Encapsulates provider-specific MCP config generation and injection."""

    @abstractmethod
    def inject(
        self,
        agent: AgentConfig,
        servers: list[McpServerSpec],
        feature_dir: Path,
        project_dir: Path,
    ) -> AgentConfig | None:
        """Returns modified AgentConfig, or None if injection not possible."""

    @abstractmethod
    def cleanup(self, feature_dir: Path, project_dir: Path) -> None:
        """Remove generated config artifacts. Must be idempotent."""


def _merge_env(current: dict[str, str] | None, extra: dict[str, str]) -> dict[str, str]:
    merged = dict(current or {})
    merged.update(extra)
    return merged


def _server_stanza(server: McpServerSpec) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": "python3",
        "args": ["-m", server.module],
        "env": server.env,
    }


class ClaudeInjector(McpInjector):
    def inject(
        self,
        agent: AgentConfig,
        servers: list[McpServerSpec],
        feature_dir: Path,
        project_dir: Path,
    ) -> AgentConfig | None:
        _ = project_dir
        config_path = feature_dir / "mcp_claude.json"
        config = {
            "mcpServers": {
                server.name: _server_stanza(server)
                for server in servers
            }
        }
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        args = list(agent.args or [])
        args.extend(["--mcp-config", str(config_path)])
        return replace(agent, args=args)

    def cleanup(self, feature_dir: Path, project_dir: Path) -> None:
        _ = (feature_dir, project_dir)


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _codex_server_block(server: McpServerSpec) -> str:
    lines = [
        f"[mcp_servers.{server.name}]",
        'command = "python3"',
        f"args = [{', '.join(_toml_quote(arg) for arg in ['-m', server.module])}]",
        "enabled = true",
        "",
        f"[mcp_servers.{server.name}.env]",
    ]
    for key, value in server.env.items():
        lines.append(f"{key} = {_toml_quote(value)}")
    return "\n".join(lines)


class CodexInjector(McpInjector):
    def inject(
        self,
        agent: AgentConfig,
        servers: list[McpServerSpec],
        feature_dir: Path,
        project_dir: Path,
    ) -> AgentConfig | None:
        _ = project_dir
        codex_home = feature_dir / "codex_home"
        codex_home.mkdir(parents=True, exist_ok=True)
        staged_config = codex_home / "config.toml"

        if not staged_config.exists():
            source_config = Path.home() / ".codex" / "config.toml"
            if source_config.exists():
                shutil.copy2(source_config, staged_config)
            else:
                staged_config.write_text("", encoding="utf-8")

        content = staged_config.read_text(encoding="utf-8")
        updated = content
        for server in servers:
            section_header = f"[mcp_servers.{server.name}]"
            if section_header in updated:
                continue
            block = _codex_server_block(server)
            if updated and not updated.endswith("\n"):
                updated += "\n"
            if updated.strip():
                updated += "\n"
            updated += block + "\n"

        if updated != content:
            staged_config.write_text(updated, encoding="utf-8")

        env = _merge_env(agent.env, {"CODEX_HOME": str(codex_home)})
        return replace(agent, env=env)

    def cleanup(self, feature_dir: Path, project_dir: Path) -> None:
        _ = (feature_dir, project_dir)


class GeminiInjector(McpInjector):
    _MARKER_FILE = "gemini_config_created"

    def inject(
        self,
        agent: AgentConfig,
        servers: list[McpServerSpec],
        feature_dir: Path,
        project_dir: Path,
    ) -> AgentConfig | None:
        settings_path = project_dir / ".gemini" / "settings.json"
        if settings_path.exists():
            return None

        settings_path.parent.mkdir(parents=True, exist_ok=True)
        config = {
            "mcpServers": {
                server.name: {
                    "command": "python3",
                    "args": ["-m", server.module],
                    "env": server.env,
                    "trust": True,
                }
                for server in servers
            }
        }
        settings_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        (feature_dir / self._MARKER_FILE).write_text("", encoding="utf-8")
        return agent

    def cleanup(self, feature_dir: Path, project_dir: Path) -> None:
        marker = feature_dir / self._MARKER_FILE
        if not marker.exists():
            return

        settings_path = project_dir / ".gemini" / "settings.json"
        gemini_dir = settings_path.parent

        if settings_path.exists():
            settings_path.unlink()
        if gemini_dir.exists() and not any(gemini_dir.iterdir()):
            gemini_dir.rmdir()
        if marker.exists():
            marker.unlink()


class OpenCodeInjector(McpInjector):
    def inject(
        self,
        agent: AgentConfig,
        servers: list[McpServerSpec],
        feature_dir: Path,
        project_dir: Path,
    ) -> AgentConfig | None:
        _ = project_dir
        config_path = feature_dir / "mcp_opencode.json"
        config = {
            "mcp": {
                server.name: {
                    "type": "local",
                    "command": ["python3", "-m", server.module],
                    "environment": server.env,
                    "enabled": True,
                }
                for server in servers
            }
        }
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        env = _merge_env(agent.env, {"OPENCODE_CONFIG": str(config_path)})
        return replace(agent, env=env)

    def cleanup(self, feature_dir: Path, project_dir: Path) -> None:
        _ = (feature_dir, project_dir)


INJECTORS: dict[str, McpInjector] = {
    "claude": ClaudeInjector(),
    "codex": CodexInjector(),
    "gemini": GeminiInjector(),
    "opencode": OpenCodeInjector(),
}


def setup_mcp(
    agents: dict[str, AgentConfig],
    servers: list[McpServerSpec],
    roles: Iterable[str],
    feature_dir: Path,
    project_dir: Path,
) -> dict[str, AgentConfig]:
    """Inject MCP servers for specified roles. Returns modified agents dict."""

    updated_agents = dict(agents)
    for role in roles:
        agent = updated_agents.get(role)
        if agent is None:
            continue
        injector = INJECTORS.get(agent.cli)
        if injector is None:
            continue
        injected = injector.inject(agent, servers, feature_dir, project_dir)
        if injected is not None:
            updated_agents[role] = injected
    return updated_agents


def cleanup_mcp(feature_dir: Path, project_dir: Path) -> None:
    """Idempotent cleanup of all generated MCP config files."""

    seen: set[int] = set()
    for injector in INJECTORS.values():
        injector_id = id(injector)
        if injector_id in seen:
            continue
        seen.add(injector_id)
        injector.cleanup(feature_dir, project_dir)
