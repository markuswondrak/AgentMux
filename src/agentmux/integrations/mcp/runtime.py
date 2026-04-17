from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from ...shared.models import AgentConfig, ProjectPaths
from .configurators import _python_command
from .models import ROLE_TOOLS, McpServerSpec


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


def _role_servers(servers: list[McpServerSpec], role: str) -> list[McpServerSpec]:
    """Return server specs filtered to only the tools the given role needs.

    Adds AGENTMUX_ALLOWED_TOOLS to each server's env so the spawned MCP
    process registers only the relevant subset of tools.
    """
    allowed = ROLE_TOOLS.get(role)
    if allowed is None:
        return servers
    allowed_csv = ",".join(sorted(allowed))
    return [
        McpServerSpec(
            name=s.name,
            module=s.module,
            env={**s.env, "AGENTMUX_ALLOWED_TOOLS": allowed_csv},
        )
        for s in servers
    ]


def create_runtime_mcp_config(
    servers: list[McpServerSpec],
    project_dir: Path,
    role: str | None = None,
    feature_dir: Path | None = None,
) -> Path:
    """Generate a runtime MCP server config JSON under .agentmux/.

    When *role* is given the file is named ``mcp_servers_<role>.json`` so that
    each agent gets its own config with a role-specific ``AGENTMUX_ALLOWED_TOOLS``
    env var.  Without *role* the shared ``mcp_servers.json`` is written instead.

    When *feature_dir* is given, ``FEATURE_DIR`` is added to each server's env
    so that MCP tools (e.g. ``submit_research_done``) can locate session files
    without requiring the agent to re-pass the path in every tool call.

    The file is only rewritten when its content would change.

    Args:
        servers: MCP server specifications (may carry role-specific env).
        project_dir: Project root directory where .agentmux/ lives.
        role: Optional role name used to derive the config file name.
        feature_dir: Optional session feature directory; injected as FEATURE_DIR.

    Returns:
        Absolute path to the generated config file.
    """
    paths = ProjectPaths.from_project(project_dir)
    paths.root.mkdir(parents=True, exist_ok=True)
    filename = f"mcp_servers_{role}.json" if role else "mcp_servers.json"
    config_path = paths.root / filename

    mcp_servers: dict[str, object] = {}
    for server in servers:
        server_env: dict[str, str] = {
            "PYTHONPATH": str(project_dir),
            "PROJECT_DIR": str(project_dir),
        }
        if feature_dir is not None:
            server_env["FEATURE_DIR"] = str(feature_dir)
        server_env.update(server.env)
        mcp_servers[server.name] = {
            "type": "stdio",
            "command": _python_command(),
            "args": ["-m", server.module],
            "env": server_env,
        }

    config = {"mcpServers": mcp_servers}

    # Skip write when content is unchanged (avoid spurious mtime bumps)
    if config_path.exists():
        try:
            existing_config = json.loads(config_path.read_text(encoding="utf-8"))
            if existing_config == config:
                return config_path
        except (OSError, json.JSONDecodeError):
            pass

    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def setup_mcp(
    agents: dict[str, AgentConfig],
    servers: list[McpServerSpec],
    roles: list[str],
    feature_dir: Path,
    project_dir: Path,
) -> dict[str, AgentConfig]:
    """Inject runtime env for MCP-aware roles without mutating user auth/config state.

    Each role receives only the MCP tools it actually needs (see ROLE_TOOLS).
    For Claude agents a per-role ``mcp_servers_<role>.json`` config is generated
    so the MCP server process is started with the correct AGENTMUX_ALLOWED_TOOLS.
    For all other CLI providers AGENTMUX_ALLOWED_TOOLS is injected into the agent
    process env, where it is inherited by any MCP server sub-process.

    ``FEATURE_DIR`` and ``PROJECT_DIR`` are injected into every MCP-enabled
    agent's process env so that MCP tools such as ``submit_research_done`` can
    locate session files without requiring the agent to re-pass the path in each
    tool call.  For Claude agents these vars are also written into the per-role
    ``mcp_servers_<role>.json`` so that the MCP server sub-process (which Claude
    starts from the JSON config) inherits them too.
    """
    updated_agents = dict(agents)
    for role in roles:
        agent = updated_agents.get(role)
        if agent is None:
            continue

        role_specific_servers = _role_servers(servers, role)

        # Inject runtime env vars (PYTHONPATH + AGENTMUX_ALLOWED_TOOLS for non-Claude)
        env = dict(agent.env or {})
        for server in role_specific_servers:
            env.update(_runtime_env(server, project_dir, env))

        # Inject session paths so MCP tools can resolve files without re-passing them
        env["FEATURE_DIR"] = str(feature_dir)
        env["PROJECT_DIR"] = str(project_dir)

        # For Claude agents, generate a per-role config and pass it via --mcp-config
        args = list(agent.args or [])
        if agent.cli == "claude" and "--mcp-config" not in args:
            role_config_path = create_runtime_mcp_config(
                role_specific_servers, project_dir, role=role, feature_dir=feature_dir
            )
            args.extend(["--mcp-config", str(role_config_path)])

        updated_agents[role] = replace(agent, env=env, args=args)
    return updated_agents


def cleanup_mcp(feature_dir: Path, project_dir: Path) -> None:
    """No-op placeholder; runtime MCP setup no longer creates per-feature artifacts."""

    _ = (feature_dir, project_dir)
