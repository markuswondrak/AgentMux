from __future__ import annotations

from dataclasses import dataclass

from ..shared.models import AgentConfig
from . import load_builtin_catalog


@dataclass(frozen=True)
class Provider:
    name: str
    cli: str
    model_flag: str
    trust_snippet: str | None
    default_args: dict[str, list[str]]
    batch_subcommand: str | None = None
    single_coder: bool = False
    default_model: str | None = None
    default_role_args: list[str] | None = None


def _build_builtin_providers() -> dict[str, Provider]:
    raw = load_builtin_catalog()
    providers = raw.get("providers", {})
    result: dict[str, Provider] = {}
    for name, provider in providers.items():
        # Parse default_role_args (shared across all roles)
        default_role_args = [str(arg) for arg in provider.get("default_role_args", [])]

        # Parse default_model for the provider
        default_model = provider.get("default_model")

        # Build role_args by merging default_role_args with role-specific args
        role_args: dict[str, list[str]] = {}
        for role, specific_args in provider.get("role_args", {}).items():
            # Defaults come first, then specific args (specific can override/extend)
            merged = default_role_args + [str(arg) for arg in specific_args]
            role_args[str(role)] = merged

        result[str(name)] = Provider(
            name=str(name),
            cli=str(provider.get("command", name)),
            model_flag=str(provider.get("model_flag", "--model")),
            trust_snippet=provider.get("trust_snippet"),
            default_args=role_args,
            batch_subcommand=provider.get("batch_subcommand"),
            single_coder=bool(provider.get("single_coder", False)),
            default_model=default_model,
            default_role_args=default_role_args if default_role_args else None,
        )
    return result


PROVIDERS: dict[str, Provider] = _build_builtin_providers()


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

    return AgentConfig(
        role=role,
        cli=provider.cli,
        model=model,
        model_flag=provider.model_flag,
        args=list(args),
        trust_snippet=provider.trust_snippet,
        batch_subcommand=provider.batch_subcommand,
        single_coder=provider.single_coder,
    )
