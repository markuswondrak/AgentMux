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


def _build_builtin_providers() -> dict[str, Provider]:
    raw = load_builtin_catalog()
    providers = raw.get("providers", {})
    result: dict[str, Provider] = {}
    for name, provider in providers.items():
        result[str(name)] = Provider(
            name=str(name),
            cli=str(provider.get("command", name)),
            model_flag=str(provider.get("model_flag", "--model")),
            trust_snippet=provider.get("trust_snippet"),
            default_args={
                str(role): [str(arg) for arg in args]
                for role, args in dict(provider.get("role_args", {})).items()
            },
            batch_subcommand=provider.get("batch_subcommand"),
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

    # In v2, model is specified directly in role_config
    model = str(role_config.get("model", "sonnet"))

    args = role_config.get("args")
    if args is None:
        args = provider.default_args.get(role, [])

    return AgentConfig(
        role=role,
        cli=provider.cli,
        model=model,
        model_flag=provider.model_flag,
        args=list(args),
        trust_snippet=provider.trust_snippet,
        batch_subcommand=provider.batch_subcommand,
    )
