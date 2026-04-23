from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from ...shared.models import AgentConfig
from .models import McpServerSpec


def _python_command() -> str:
    return sys.executable or "python3"


def _persistent_stdio_server(server: McpServerSpec) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": _python_command(),
        "args": ["-m", server.module],
    }


def _persistent_local_server(server: McpServerSpec) -> dict[str, object]:
    return {
        "type": "local",
        "command": [_python_command(), "-m", server.module],
        "enabled": True,
    }


def _copilot_local_server(server: McpServerSpec) -> dict[str, object]:
    """Build a Copilot CLI-compatible local MCP server entry.

    Copilot CLI uses 'command' as a string and 'args' as a separate array,
    unlike OpenCode which uses 'command' as a list.
    See: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
    """
    return {
        "type": "local",
        "command": _python_command(),
        "args": ["-m", server.module],
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
            f"Warning: Agentmux MCP server not configured for {self.provider} "
            f"({roles_label}) at {path}. "
            "The pipeline will not function — run 'agentmux init' to configure."
        )

    def configured_message(self, server: McpServerSpec, project_dir: Path) -> str:
        path = self.config_path(project_dir)
        return f"Configured agentmux MCP tools for {self.provider} at {path}."

    def skipped_message(self, server: McpServerSpec) -> str:
        return (
            f"Warning: Skipped agentmux MCP setup for {self.provider}. "
            "The pipeline will not function without it — "
            "re-run 'agentmux init' to configure."
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
            f"Agentmux requires its MCP server for claude ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
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
            f"Agentmux requires its MCP server for gemini ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
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
            f"Agentmux requires its MCP server for opencode ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
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
            f"Agentmux requires its MCP server for codex ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
        )

    def configured_message(self, server: McpServerSpec, project_dir: Path) -> str:
        path = self.config_path(project_dir)
        return f"Configured agentmux MCP tools for codex at {path}."


class QwenConfigurator(JsonMcpConfigurator):
    provider = "qwen"

    def config_path(self, project_dir: Path) -> Path:
        _ = project_dir
        return Path.home() / ".qwen" / "settings.json"

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
            f"Agentmux requires its MCP server for qwen ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
        )


class CopilotConfigurator(JsonMcpConfigurator):
    """Installs agentmux MCP server into GitHub Copilot CLI config.

    Config path: ~/.copilot/mcp-config.json
    Source: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers
    """

    provider = "copilot"

    def config_path(self, project_dir: Path) -> Path:
        _ = project_dir
        return Path.home() / ".copilot" / "mcp-config.json"

    def has_server(self, server: McpServerSpec, project_dir: Path) -> bool:
        data = self._load_json(project_dir)
        servers = data.get("mcpServers", {})
        return isinstance(servers, dict) and server.name in servers

    def install(self, server: McpServerSpec, project_dir: Path) -> None:
        data = self._load_json(project_dir)
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        servers[server.name] = _copilot_local_server(server)
        data["mcpServers"] = servers
        self._write_json(data, project_dir)

    def prompt_message(
        self, server: McpServerSpec, project_dir: Path, roles_label: str
    ) -> str:
        path = self.config_path(project_dir)
        return (
            f"Agentmux requires its MCP server for copilot ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
        )


class CursorConfigurator(JsonMcpConfigurator):
    """Installs agentmux MCP server into Cursor project config.

    Config path: <project_dir>/.cursor/mcp.json
    Uses the Claude Desktop mcpServers JSON format.
    """

    provider = "cursor"

    def config_path(self, project_dir: Path) -> Path:
        return project_dir / ".cursor" / "mcp.json"

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
            f"Agentmux requires its MCP server for cursor ({roles_label}) "
            f"to coordinate agents. Install at {path}?"
        )


CONFIGURATORS: dict[str, PersistentMcpConfigurator] = {
    "claude": ClaudeConfigurator(),
    "codex": CodexConfigurator(),
    "copilot": CopilotConfigurator(),
    "cursor": CursorConfigurator(),
    "gemini": GeminiConfigurator(),
    "opencode": OpenCodeConfigurator(),
    "qwen": QwenConfigurator(),
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
    if isinstance(configurator, CopilotConfigurator):
        expected_entry = _copilot_local_server(server)
    else:
        expected_entry = _persistent_stdio_server(server)

    # Compare relevant fields (type, command, args)
    if existing_entry.get("type") != expected_entry.get("type"):
        return False
    if existing_entry.get("command") != expected_entry.get("command"):
        return False
    return existing_entry.get("args") == expected_entry.get("args")
