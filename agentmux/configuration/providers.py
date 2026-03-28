from __future__ import annotations

from dataclasses import dataclass

from . import load_builtin_catalog
from ..shared.models import AgentConfig


@dataclass(frozen=True)
class Provider:
    name: str
    cli: str
    model_flag: str
    models: dict[str, str]
    trust_snippet: str | None
    default_args: dict[str, list[str]]


def _build_builtin_providers() -> dict[str, Provider]:
    raw = load_builtin_catalog()
    launchers = raw.get("launchers", {})
    profiles = raw.get("profiles", {})
    providers: dict[str, Provider] = {}
    for name, launcher in launchers.items():
        providers[str(name)] = Provider(
            name=str(name),
            cli=str(launcher.get("command", name)),
            model_flag=str(launcher.get("model_flag", "--model")),
            models={
                str(profile_name): str(profile_cfg["model"])
                for profile_name, profile_cfg in dict(profiles.get(name, {})).items()
            },
            trust_snippet=launcher.get("trust_snippet"),
            default_args={
                str(role): [str(arg) for arg in args]
                for role, args in dict(launcher.get("role_args", {})).items()
            },
        )
    return providers


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

    profile = str(role_config.get("profile", "standard"))
    try:
        model = provider.models[profile]
    except KeyError as exc:
        valid_profiles = ", ".join(sorted(provider.models))
        raise ValueError(
            f"Unknown profile '{profile}' for provider '{provider.name}'. Expected one of: {valid_profiles}"
        ) from exc

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
    )
