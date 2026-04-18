from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from ...shared.models import AgentConfig, ProjectPaths
from .configurators import _provider_key, _python_command
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


def _inject_cursor_mcp_env(
    project_dir: Path,
) -> None:
    """Embed stable env vars into .cursor/mcp.json for each MCP server.

    Cursor CLI does not inherit the parent process env when spawning MCP server
    subprocesses, so PYTHONPATH and PROJECT_DIR must be written directly into
    .cursor/mcp.json. These values are project-specific but stable (do not
    change between sessions), so they do not trigger Cursor's MCP approval modal
    on subsequent runs.

    Session-specific values (FEATURE_DIR, AGENTMUX_ALLOWED_TOOLS) are NOT
    written here; they go into .agentmux/.active_session via
    _write_cursor_active_session().  Any stale copies of those keys left by
    older versions of AgentMux are removed here as a one-time migration.
    """
    config_path = project_dir / ".cursor" / "mcp.json"
    if not config_path.exists():
        return

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    mcp_servers = data.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        return

    stable_env: dict[str, str] = {
        "PYTHONPATH": _compose_pythonpath(project_dir, os.environ.get("PYTHONPATH")),
        "PROJECT_DIR": str(project_dir),
    }

    changed = False
    for _server_name, entry in mcp_servers.items():
        if not isinstance(entry, dict):
            continue
        current_env: dict[str, str] = dict(entry.get("env") or {})
        new_env = {k: v for k, v in current_env.items()}
        new_env.update(stable_env)
        # Remove session-specific keys that must not live in the persistent config
        new_env.pop("FEATURE_DIR", None)
        new_env.pop("AGENTMUX_ALLOWED_TOOLS", None)
        if new_env != current_env:
            entry["env"] = new_env
            changed = True

    if changed:
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_cursor_active_session(
    project_dir: Path,
    role_servers_list: list[list[McpServerSpec]],
    feature_dir: Path,
) -> None:
    """Write session-specific MCP values to .agentmux/.active_session.

    Cursor CLI does not pass environment variables to its MCP server
    subprocesses.  FEATURE_DIR and AGENTMUX_ALLOWED_TOOLS change on every
    session, so instead of writing them into .cursor/mcp.json (which triggers
    Cursor's MCP approval modal on each change), they are written here.  The
    MCP server reads this file as a fallback when the env vars are absent.

    Only one active Cursor session per project is supported at a time — a
    concurrent second session would overwrite this file.
    """
    merged_tools: set[str] = set()
    for role_servers in role_servers_list:
        for spec in role_servers:
            allowed = spec.env.get("AGENTMUX_ALLOWED_TOOLS", "")
            if allowed:
                merged_tools.update(t for t in allowed.split(",") if t)

    session_data: dict[str, str] = {"feature_dir": str(feature_dir)}
    if merged_tools:
        session_data["allowed_tools"] = ",".join(sorted(merged_tools))

    active_session_path = project_dir / ".agentmux" / ".active_session"
    active_session_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to a temp file alongside the target, then rename
    tmp_path = active_session_path.with_suffix(".active_session.tmp")
    tmp_path.write_text(json.dumps(session_data, indent=2) + "\n", encoding="utf-8")
    tmp_path.rename(active_session_path)


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
    cursor_role_servers: list[list[McpServerSpec]] = []
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

        # Track cursor agents so we can update .cursor/mcp.json after the loop
        if _provider_key(agent) == "cursor":
            cursor_role_servers.append(role_specific_servers)

        updated_agents[role] = replace(agent, env=env, args=args)

    if cursor_role_servers:
        _inject_cursor_mcp_env(project_dir)
        _write_cursor_active_session(project_dir, cursor_role_servers, feature_dir)

    return updated_agents


def cleanup_mcp(feature_dir: Path, project_dir: Path) -> None:
    """No-op placeholder; runtime MCP setup no longer creates per-feature artifacts."""

    _ = (feature_dir, project_dir)
