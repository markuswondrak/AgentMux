from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from ...shared.models import AgentConfig, ProjectPaths
from .configurators import _python_command
from .models import McpServerSpec


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


def create_runtime_mcp_config(servers: list[McpServerSpec], project_dir: Path) -> Path:
    """Generate .agentmux/mcp_servers.json with runtime MCP server definitions.

    This creates a runtime config file containing absolute paths specific to the
    current environment. The file is written only if content differs from existing.

    Args:
        servers: List of MCP server specifications to include
        project_dir: Project root directory where .agentmux/ will be created

    Returns:
        Absolute path to the generated config file
    """
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


def setup_mcp(
    agents: dict[str, AgentConfig],
    servers: list[McpServerSpec],
    roles: list[str],
    feature_dir: Path,
    project_dir: Path,
) -> dict[str, AgentConfig]:
    """Inject runtime env for MCP-aware roles without mutating
    user auth/config state."""

    _ = feature_dir

    # Create runtime MCP config file
    runtime_config_path = create_runtime_mcp_config(servers, project_dir)

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
