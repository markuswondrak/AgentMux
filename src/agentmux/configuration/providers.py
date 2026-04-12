from __future__ import annotations

from dataclasses import dataclass

from ..shared.models import AgentConfig, BatchCommand, BatchCommandMode
from . import load_builtin_catalog


@dataclass(frozen=True)
class Provider:
    name: str
    cli: str
    model_flag: str | None
    trust_snippet: str | None
    default_args: dict[str, list[str]]
    batch_command: BatchCommand | None = None
    single_coder: bool = False
    default_model: str | None = None
    default_role_args: list[str] | None = None
    model_args: dict[str, list[str]] | None = None


def _build_builtin_providers() -> dict[str, Provider]:
    raw = load_builtin_catalog()
    providers = raw.get("providers", {})
    result: dict[str, Provider] = {}
    for name, provider in providers.items():
        # Parse default_role_args (shared across all roles)
        default_role_args = [str(arg) for arg in provider.get("default_role_args", [])]

        # Parse default_model for the provider
        default_model = provider.get("default_model")

        # Parse model_args (model-specific additional arguments)
        raw_model_args = provider.get("model_args", {})
        model_args: dict[str, list[str]] = {}
        for model_id, args in raw_model_args.items():
            model_args[str(model_id)] = [str(a) for a in args]

        # Build role_args by merging default_role_args with role-specific args
        role_args: dict[str, list[str]] = {}
        for role, specific_args in provider.get("role_args", {}).items():
            # Defaults come first, then specific args (specific can override/extend)
            merged = default_role_args + [str(arg) for arg in specific_args]
            role_args[str(role)] = merged

        result[str(name)] = Provider(
            name=str(name),
            cli=str(provider.get("command", name)),
            model_flag=provider.get("model_flag"),
            trust_snippet=provider.get("trust_snippet"),
            default_args=role_args,
            batch_command=_parse_batch_command(provider),
            single_coder=bool(provider.get("single_coder", False)),
            default_model=default_model,
            default_role_args=default_role_args if default_role_args else None,
            model_args=model_args if model_args else None,
        )
    return result


def _parse_batch_command(provider: dict) -> BatchCommand | None:
    """Parse batch_command from provider config, supporting both old and new formats.

    Old format (deprecated):
        batch_subcommand: "exec"  # or "-p" or "run"

    New format:
        batch_command:
            verb: "exec"
            mode: "stdin"

    Also handles pre-parsed dicts from __init__.py where mode may already
    be a BatchCommandMode enum or None (for string fallback).
    """
    # New format takes precedence
    raw_batch = provider.get("batch_command")
    if raw_batch is not None:
        if isinstance(raw_batch, dict):
            verb = str(raw_batch.get("verb", ""))
            mode_raw = raw_batch.get("mode")
            # Already parsed as enum?
            if isinstance(mode_raw, BatchCommandMode):
                return BatchCommand(verb=verb, mode=mode_raw)
            if mode_raw is not None:
                mode_str = str(mode_raw)
                mode = BatchCommandMode(mode_str)
            else:
                # String fallback: infer mode from verb
                if verb.startswith("-"):
                    mode = BatchCommandMode.FLAG
                elif verb == "exec" and provider.get("command") == "codex":
                    mode = BatchCommandMode.STDIN
                else:
                    mode = BatchCommandMode.POSITIONAL
            return BatchCommand(verb=verb, mode=mode)
        # Direct string in provider dict (shouldn't happen, but handle it)
        verb = str(raw_batch)
        if verb.startswith("-"):
            mode = BatchCommandMode.FLAG
        elif verb == "exec" and provider.get("command") == "codex":
            mode = BatchCommandMode.STDIN
        else:
            mode = BatchCommandMode.POSITIONAL
        return BatchCommand(verb=verb, mode=mode)

    # Legacy format compatibility
    legacy = provider.get("batch_subcommand")
    if legacy is not None:
        verb = str(legacy)
        if verb.startswith("-"):
            mode = BatchCommandMode.FLAG
        elif verb == "exec" and provider.get("command") == "codex":
            mode = BatchCommandMode.STDIN
        else:
            mode = BatchCommandMode.POSITIONAL
        return BatchCommand(verb=verb, mode=mode)

    return None


PROVIDERS: dict[str, Provider] = _build_builtin_providers()


def get_known_providers() -> list[str]:
    """Return a sorted list of all known provider names."""
    return sorted(PROVIDERS.keys())


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROVIDERS))
        raise ValueError(
            f"Unknown provider '{name}'. Expected one of: {available}"
        ) from exc


def resolve_agent(
    global_provider: Provider, role: str, role_config: dict
) -> AgentConfig:
    provider_name = role_config.get("provider")
    provider = get_provider(provider_name) if provider_name else global_provider

    # In v2, model is specified directly in role_config, fallback to provider
    # default, then "sonnet"
    model = str(role_config.get("model", provider.default_model or "sonnet"))

    args = role_config.get("args")
    if args is None:
        # Use role-specific args if defined, otherwise fall back to provider's
        # default_role_args
        args = provider.default_args.get(role, provider.default_role_args or [])

    # Append model-specific args if defined for this model
    model_extra = provider.model_args.get(model, []) if provider.model_args else []
    if model_extra:
        args = list(args) + model_extra

    return AgentConfig(
        role=role,
        cli=provider.cli,
        model=model,
        model_flag=provider.model_flag,
        args=list(args),
        trust_snippet=provider.trust_snippet,
        batch_command=provider.batch_command,
        single_coder=provider.single_coder,
    )
