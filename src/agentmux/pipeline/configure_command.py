from __future__ import annotations

import sys
from pathlib import Path

import yaml

from ..configuration import load_layered_config
from ..integrations.mcp import OpenCodeAgentConfigurator
from ..shared.models import OPENCODE_AGENT_ROLES as ROLES
from .init_command import KNOWN_PROVIDERS, _select, _text, detect_clis


def run_configure(
    *,
    provider: str | None,
    project_dir: Path,
    role: str | None = None,
    model: str | None = None,
    agent: str | None = None,
    force: bool = False,
    global_scope: bool = False,
) -> int:
    """Entry point for `agentmux configure` command.

    Args:
        provider: The provider to configure (e.g., "claude", "opencode")
        project_dir: The project directory containing .agentmux/config.yaml
        role: Role name for non-interactive model update (--role)
        model: Model name for non-interactive model update (--model)
        agent: Agent name for non-interactive agent entries (--agent)
        force: Force overwrite existing agent entries (--force)
        global_scope: Use global scope for opencode config
            (~/.config/opencode/opencode.json)

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Guard condition 1: Config must exist
    config_path = project_dir / ".agentmux" / "config.yaml"
    if not config_path.exists():
        print("No config found. Run `agentmux init` first.", file=sys.stderr)
        raise SystemExit(1)

    # Guard condition 2: Provider must be known (if specified)
    if provider is not None and provider not in KNOWN_PROVIDERS:
        known_list = ", ".join(KNOWN_PROVIDERS)
        print(
            f"Unknown provider '{provider}'. Known providers: {known_list}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Mode dispatch based on arguments
    if role is not None and model is not None:
        # --role + --model mode (non-interactive model update)
        return _handle_role_model_mode(project_dir, config_path, role, model)

    if agent is not None:
        # --agent mode (non-interactive agent entries)
        return _handle_agent_mode(project_dir, provider, agent, force, global_scope)

    # Interactive mode (neither --role/--model nor --agent specified)
    return _handle_interactive_mode(project_dir, provider, config_path)


def _handle_role_model_mode(
    project_dir: Path, config_path: Path, role: str, model: str
) -> int:
    """Handle --role + --model non-interactive mode."""
    # Validate role ∈ ROLES → SystemExit(1) if not
    if role not in ROLES:
        print(
            f"Unknown role '{role}'. Known roles: {', '.join(ROLES)}", file=sys.stderr
        )
        raise SystemExit(1)

    # Load raw YAML from .agentmux/config.yaml (round-trip to preserve order)
    with open(config_path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f) or {}

    # Ensure roles[role] dict exists
    roles_section = raw_config.setdefault("roles", {})
    if not isinstance(roles_section, dict):
        roles_section = {}
        raw_config["roles"] = roles_section

    role_entry = roles_section.setdefault(role, {})
    if not isinstance(role_entry, dict):
        role_entry = {}
        roles_section[role] = role_entry

    # Set the model value
    role_entry["model"] = model

    # Write back preserving key order
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw_config, f, sort_keys=False)

    print(f"✓ roles.{role}.model set to {model}")
    return 0


def _handle_agent_mode(
    project_dir: Path,
    provider: str | None,
    agent: str,
    force: bool,
    global_scope: bool,
) -> int:
    """Handle --agent non-interactive mode."""
    if provider != "opencode":
        print(f"No agent entries needed for {provider}")
        return 0

    configurator = OpenCodeAgentConfigurator()
    target_path = configurator.config_path(project_dir, global_scope=global_scope)

    if agent == "all":
        results = configurator.install_all_agents(target_path, force=force)
        for role_name, status in results.items():
            print(f"✓ agentmux-{role_name}: {status}")
    else:
        # Validate role
        if agent not in ROLES:
            print(
                f"Unknown role '{agent}'. Known roles: {', '.join(ROLES)}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        status = configurator.install_agent(agent, target_path, force=force)
        print(f"✓ agentmux-{agent}: {status}")

    return 0


def _handle_interactive_mode(
    project_dir: Path, provider: str | None, config_path: Path
) -> int:
    """Handle interactive mode (no --role/--model or --agent flags)."""
    # Guard: requires TTY
    if not sys.stdin.isatty():
        print(
            "Interactive mode requires a TTY. "
            "Use --role/--model or --agent for non-interactive use.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # If provider not specified, detect and select from available CLIs
    if provider is None:
        detected = detect_clis()
        available = [p for p, present in detected.items() if present]
        if not available:
            print(
                "No supported provider CLI detected. "
                "Install one of: claude, codex, gemini, opencode, copilot.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        provider = _select("Select provider", available, default=available[0])

    # Load layered config to get current models
    loaded = load_layered_config(project_dir)

    # Collect roles where agent.provider == provider or agent.cli == provider
    applicable_roles: list[str] = []
    for role_name in ROLES:
        agent_cfg = loaded.agents.get(role_name)
        if agent_cfg is None:
            continue
        if agent_cfg.provider == provider or agent_cfg.cli == provider:
            applicable_roles.append(role_name)

    if not applicable_roles:
        print(f"No roles configured for provider '{provider}'.")
        return 0

    # Prompt model per role (current model as default; Enter to keep)
    for role_name in applicable_roles:
        agent_cfg = loaded.agents[role_name]
        current_model = agent_cfg.model
        new_model = _text(
            f"Model for {role_name}",
            default=current_model,
        )
        if new_model and new_model != current_model:
            # Store the change in the raw config
            _update_raw_config(config_path, role_name, new_model)

    # For opencode: show agent entry status per role; offer to add each missing one
    if provider == "opencode":
        configurator = OpenCodeAgentConfigurator()
        target_path = configurator.config_path(project_dir, global_scope=False)
        for role_name in applicable_roles:
            if not configurator.has_agent(role_name, target_path):
                add = _select(
                    f"Add agentmux-{role_name} to opencode.json?",
                    ["yes", "no"],
                    default="yes",
                )
                if add == "yes":
                    status = configurator.install_agent(role_name, target_path)
                    print(f"✓ agentmux-{role_name}: {status}")

    return 0


def _update_raw_config(config_path: Path, role: str, model: str) -> None:
    """Update a single role's model in the raw YAML file."""
    with open(config_path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f) or {}

    roles_section = raw_config.setdefault("roles", {})
    if not isinstance(roles_section, dict):
        roles_section = {}
        raw_config["roles"] = roles_section

    role_entry = roles_section.setdefault(role, {})
    if not isinstance(role_entry, dict):
        role_entry = {}
        roles_section[role] = role_entry

    role_entry["model"] = model

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw_config, f, sort_keys=False)
