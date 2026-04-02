from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from ..shared.models import AgentConfig

try:
    import questionary
except ImportError:  # pragma: no cover - optional at import time in this environment
    questionary = None


@dataclass(frozen=True)
class McpServerSpec:
    """Provider-agnostic definition of an MCP server."""

    name: str
    module: str
    env: dict[str, str]


DEFAULT_RESEARCH_ROLES = ("architect", "product-manager")
DEFAULT_RESEARCH_SERVERS = (
    McpServerSpec(
        name="agentmux-research",
        module="agentmux.integrations.mcp_research_server",
        env={},
    ),
)


class PersistentMcpConfigurator(ABC):
    provider: str

    @abstractmethod
    def config_path(self, project_dir: Path) -> Path:
        """Returns the config file for this provider and project context."""

    @abstractmethod
    def has_server(self, server: McpServerSpec, project_dir: Path) -> bool:
        """Returns True when the named server entry already exists."""

    @abstractmethod
    def install(self, server: McpServerSpec, project_dir: Path) -> None:
        """Creates or refreshes the managed server entry."""

    @abstractmethod
    def prompt_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        """Returns the interactive prompt shown before mutating config."""

    def missing_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        path = self.config_path(project_dir)
        return (
            f"Warning: Missing MCP config for {self.provider} ({roles_label}) "
            f"at {path}. "
            "Research MCP tools will be unavailable until configured."
        )

    def configured_message(self, server: McpServerSpec, project_dir: Path) -> str:
        path = self.config_path(project_dir)
        return f"Configured MCP research tools for {self.provider} at {path}."

    def skipped_message(self, server: McpServerSpec) -> str:
        return (
            f"Skipped MCP setup for {self.provider}; research will fall back to files."
        )


def _merge_env(current: dict[str, str] | None, extra: dict[str, str]) -> dict[str, str]:
    merged = dict(current or {})
    merged.update(extra)
    return merged


def _python_command() -> str:
    return sys.executable or "python3"


def _compose_pythonpath(project_dir: Path, current: str | None) -> str:
    entries = [str(project_dir)]
    if current:
        entries.extend(part for part in current.split(os.pathsep) if part)
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if entry not in seen:
            deduped.append(entry)
            seen.add(entry)
    return os.pathsep.join(deduped)


def _runtime_env(
    server: McpServerSpec,
    project_dir: Path,
    current: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(current or {})
    env.update(server.env)
    env["PYTHONPATH"] = _compose_pythonpath(
        project_dir,
        env.get("PYTHONPATH") or os.environ.get("PYTHONPATH"),
    )
    return env


def _persistent_stdio_server(server: McpServerSpec) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": _python_command(),
        "args": ["-m", server.module],
    }


def _create_runtime_mcp_config(servers: list[McpServerSpec], project_dir: Path) -> Path:
    """Generate .agentmux/mcp_servers.json with runtime MCP server definitions.

    This creates a runtime config file containing absolute paths specific to the
    current environment. The file is written only if content differs from existing.

    Args:
        servers: List of MCP server specifications to include
        project_dir: Project root directory where .agentmux/ will be created

    Returns:
        Absolute path to the generated config file
    """
    from ..shared.models import ProjectPaths

    paths = ProjectPaths.from_project(project_dir)
    paths.root.mkdir(parents=True, exist_ok=True)
    config_path = paths.mcp_servers

    # Build the config structure with env.PYTHONPATH
    mcp_servers: dict[str, object] = {}
    for server in servers:
        mcp_servers[server.name] = {
            "type": "stdio",
            "command": _python_command(),
            "args": ["-m", server.module],
            "env": {"PYTHONPATH": str(project_dir)},
        }

    config = {"mcpServers": mcp_servers}

    # Compare with existing content to avoid unnecessary writes
    if config_path.exists():
        try:
            existing_content = config_path.read_text(encoding="utf-8")
            existing_config = json.loads(existing_content)
            if existing_config == config:
                return config_path
        except (OSError, json.JSONDecodeError):
            pass  # File exists but is invalid, proceed to overwrite

    # Write the config file
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def _persistent_local_server(server: McpServerSpec) -> dict[str, object]:
    return {
        "type": "local",
        "command": [_python_command(), "-m", server.module],
        "enabled": True,
    }


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _codex_server_block(server: McpServerSpec) -> str:
    return "\n".join(
        [
            f"[mcp_servers.{server.name}]",
            f"command = {_toml_quote(_python_command())}",
            f"args = [{', '.join(_toml_quote(arg) for arg in ['-m', server.module])}]",
            "enabled = true",
        ]
    )


def _strip_codex_server_block(content: str, server_name: str) -> str:
    headers = {
        f"[mcp_servers.{server_name}]",
        f"[mcp_servers.{server_name}.env]",
    }
    lines = content.splitlines(keepends=True)
    kept: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped in headers:
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith("["):
                index += 1
            continue
        kept.append(lines[index])
        index += 1
    return "".join(kept).rstrip()


def _default_confirm(message: str, default: bool = True) -> bool:
    if questionary is not None:
        answer = questionary.confirm(message, default=default).ask()
        return bool(default if answer is None else answer)
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(message + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


class McpAgentPreparer:
    def __init__(self, project_dir: Path, *, interactive: bool, output: TextIO) -> None:
        self.project_dir = project_dir
        self.interactive = interactive
        self.output = output

    def ensure_project_config(self, agents: dict[str, AgentConfig]) -> None:
        ensure_mcp_config(
            agents,
            list(DEFAULT_RESEARCH_SERVERS),
            DEFAULT_RESEARCH_ROLES,
            self.project_dir,
            interactive=self.interactive,
            output=self.output,
        )

    def prepare_feature_agents(
        self, agents: dict[str, AgentConfig], feature_dir: Path
    ) -> dict[str, AgentConfig]:
        return setup_mcp(
            agents,
            list(DEFAULT_RESEARCH_SERVERS),
            DEFAULT_RESEARCH_ROLES,
            feature_dir,
            self.project_dir,
        )


class JsonMcpConfigurator(PersistentMcpConfigurator):
    def _load_json(self, project_dir: Path) -> dict[str, object]:
        path = self.config_path(project_dir)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected object at top level in {path}")
        return data

    def _write_json(self, data: dict[str, object], project_dir: Path) -> None:
        path = self.config_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


class ClaudeConfigurator(JsonMcpConfigurator):
    provider = "claude"

    def config_path(self, project_dir: Path) -> Path:
        return project_dir / ".claude" / "settings.json"

    def has_server(self, server: McpServerSpec, project_dir: Path) -> bool:
        data = self._load_json(project_dir)
        servers = data.get("mcpServers", {})
        return isinstance(servers, dict) and server.name in servers

    def install(self, server: McpServerSpec, project_dir: Path) -> None:
        data = self._load_json(project_dir)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        servers[server.name] = _persistent_stdio_server(server)
        data["mcpServers"] = servers
        self._write_json(data, project_dir)

    def prompt_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        path = self.config_path(project_dir)
        return (
            f"Configure project MCP research tools for claude ({roles_label}) "
            f"at {path}?"
        )


class GeminiConfigurator(JsonMcpConfigurator):
    provider = "gemini"

    def config_path(self, project_dir: Path) -> Path:
        return project_dir / ".gemini" / "settings.json"

    def has_server(self, server: McpServerSpec, project_dir: Path) -> bool:
        data = self._load_json(project_dir)
        servers = data.get("mcpServers", {})
        return isinstance(servers, dict) and server.name in servers

    def install(self, server: McpServerSpec, project_dir: Path) -> None:
        data = self._load_json(project_dir)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        servers[server.name] = {
            "command": _python_command(),
            "args": ["-m", server.module],
            "trust": True,
        }
        data["mcpServers"] = servers
        self._write_json(data, project_dir)

    def prompt_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        path = self.config_path(project_dir)
        return (
            f"Configure project MCP research tools for gemini ({roles_label}) "
            f"at {path}?"
        )


class OpenCodeConfigurator(JsonMcpConfigurator):
    provider = "opencode"

    def config_path(self, project_dir: Path) -> Path:
        return project_dir / "opencode.json"

    def has_server(self, server: McpServerSpec, project_dir: Path) -> bool:
        data = self._load_json(project_dir)
        servers = data.get("mcp", {})
        return isinstance(servers, dict) and server.name in servers

    def install(self, server: McpServerSpec, project_dir: Path) -> None:
        data = self._load_json(project_dir)
        servers = data.get("mcp")
        if not isinstance(servers, dict):
            servers = {}
        servers[server.name] = _persistent_local_server(server)
        data["mcp"] = servers
        self._write_json(data, project_dir)

    def prompt_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        path = self.config_path(project_dir)
        return (
            f"Configure project MCP research tools for opencode ({roles_label}) "
            f"at {path}?"
        )


class CodexConfigurator(PersistentMcpConfigurator):
    provider = "codex"

    def config_path(self, project_dir: Path) -> Path:
        _ = project_dir
        return Path.home() / ".codex" / "config.toml"

    def has_server(self, server: McpServerSpec, project_dir: Path) -> bool:
        path = self.config_path(project_dir)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        return f"[mcp_servers.{server.name}]" in content

    def install(self, server: McpServerSpec, project_dir: Path) -> None:
        path = self.config_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = _strip_codex_server_block(content, server.name)
        block = _codex_server_block(server)
        if updated and not updated.endswith("\n"):
            updated += "\n"
        if updated.strip():
            updated += "\n"
        updated += block + "\n"
        if updated != content:
            path.write_text(updated, encoding="utf-8")

    def prompt_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        path = self.config_path(project_dir)
        return (
            f"Codex configures MCP servers in {path}. "
            f"Configure agentmux-research for codex ({roles_label}) there?"
        )

    def configured_message(self, server: McpServerSpec, project_dir: Path) -> str:
        path = self.config_path(project_dir)
        return f"Configured codex MCP research tools at {path}."


CONFIGURATORS: dict[str, PersistentMcpConfigurator] = {
    "claude": ClaudeConfigurator(),
    "codex": CodexConfigurator(),
    "gemini": GeminiConfigurator(),
    "opencode": OpenCodeConfigurator(),
}


def _provider_key(agent: AgentConfig) -> str | None:
    if agent.provider and agent.provider in CONFIGURATORS:
        return agent.provider
    if agent.cli in CONFIGURATORS:
        return agent.cli
    return None


def _required_configurators(
    agents: dict[str, AgentConfig],
    roles: Iterable[str],
) -> dict[str, tuple[PersistentMcpConfigurator, tuple[str, ...]]]:
    mapping: dict[str, list[str]] = {}
    for role in roles:
        agent = agents.get(role)
        if agent is None:
            continue
        provider = _provider_key(agent)
        if provider is None:
            continue
        mapping.setdefault(provider, []).append(role)
    return {
        provider: (CONFIGURATORS[provider], tuple(sorted(set(provider_roles))))
        for provider, provider_roles in mapping.items()
    }


def _server_entry_matches(
    configurator: PersistentMcpConfigurator, server: McpServerSpec, project_dir: Path
) -> bool:
    """Check if existing server entry matches what would be generated.

    Returns True if the entry exists and matches the generated config,
    False if it doesn't exist or differs.
    """
    if not configurator.has_server(server, project_dir):
        return False

    # Load existing entry from config file
    existing_entry = None
    if isinstance(configurator, JsonMcpConfigurator):
        try:
            data = configurator._load_json(project_dir)
            servers = data.get("mcpServers", {})
            if isinstance(servers, dict):
                existing_entry = servers.get(server.name)
        except (OSError, json.JSONDecodeError, ValueError):
            return False
    elif isinstance(configurator, CodexConfigurator):
        # For Codex (TOML), we check if the block exists with correct command/args
        path = configurator.config_path(project_dir)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            expected_command = _python_command()
            expected_args = f'["-m", "{server.module}"]'
            if (
                f"[mcp_servers.{server.name}]" in content
                and f'command = "{expected_command}"' in content
                and expected_args in content
            ):
                return True
        return False

    if existing_entry is None:
        return False

    # Compare to what would be generated
    expected_entry = _persistent_stdio_server(server)

    # Compare relevant fields (type, command, args)
    if existing_entry.get("type") != expected_entry.get("type"):
        return False
    if existing_entry.get("command") != expected_entry.get("command"):
        return False
    return existing_entry.get("args") == expected_entry.get("args")


def ensure_mcp_config(
    agents: dict[str, AgentConfig],
    servers: list[McpServerSpec],
    roles: Iterable[str],
    project_dir: Path,
    *,
    interactive: bool | None = None,
    output: TextIO | None = None,
    confirm: Callable[[str], bool] | None = None,
) -> None:
    """Ensure provider-native MCP config exists for the selected roles."""

    if interactive is None:
        interactive = sys.stdin.isatty()
    writer = output or sys.stdout
    ask = confirm or _default_confirm

    if not servers:
        return

    configurators = _required_configurators(agents, roles)
    for server in servers:
        for _provider, (configurator, provider_roles) in configurators.items():
            # Check if server exists and matches expected config
            if _server_entry_matches(configurator, server, project_dir):
                # Entry exists and is correct, skip install
                continue

            if configurator.has_server(server, project_dir):
                # Entry exists but differs, install to refresh
                configurator.install(server, project_dir)
                continue

            roles_label = ", ".join(provider_roles)
            if not interactive:
                print(
                    configurator.missing_message(server, project_dir, roles_label),
                    file=writer,
                )
                continue

            message = configurator.prompt_message(server, project_dir, roles_label)
            if ask(message):
                configurator.install(server, project_dir)
                print(configurator.configured_message(server, project_dir), file=writer)
            else:
                print(configurator.skipped_message(server), file=writer)


def setup_mcp(
    agents: dict[str, AgentConfig],
    servers: list[McpServerSpec],
    roles: Iterable[str],
    feature_dir: Path,
    project_dir: Path,
) -> dict[str, AgentConfig]:
    """Inject runtime env for MCP-aware roles without mutating
    user auth/config state."""

    _ = feature_dir

    # Create runtime MCP config file
    runtime_config_path = _create_runtime_mcp_config(servers, project_dir)

    updated_agents = dict(agents)
    for role in roles:
        agent = updated_agents.get(role)
        if agent is None:
            continue

        # Inject runtime env vars
        env = dict(agent.env or {})
        for server in servers:
            env.update(_runtime_env(server, project_dir, env))

        # For Claude agents, append --mcp-config flag
        args = list(agent.args or [])
        if agent.cli == "claude" and "--mcp-config" not in args:
            args.extend(["--mcp-config", str(runtime_config_path)])

        updated_agents[role] = replace(agent, env=env, args=args)
    return updated_agents


def cleanup_mcp(feature_dir: Path, project_dir: Path) -> None:
    """No-op placeholder; runtime MCP setup no longer creates per-feature artifacts."""

    _ = (feature_dir, project_dir)
