"""Canonical attribute resolution helpers for AgentConfig construction.

All priority chains for AgentConfig attributes are defined here — once.
Both _resolve_loaded_config (merged config path) and resolve_agent (builtin
provider path) call these functions, ensuring consistent behaviour.

Priority order for each attribute:
  model : role-specific > global default > provider default > "sonnet" fallback
  args  : role-specific (if explicitly set) > provider default for this role
  model_extra_args : looked up by resolved model name in provider's model_args map
"""

from __future__ import annotations


def resolve_model(
    role_model: str | None,
    global_default: str | None,
    provider_default: str | None,
) -> str:
    """Return the first non-None model in priority order, or 'sonnet' as fallback."""
    return next(
        (m for m in (role_model, global_default, provider_default) if m is not None),
        "sonnet",
    )


def resolve_args(
    role_args: list[str] | None,
    provider_default: list[str],
) -> list[str]:
    """Return role args if explicitly configured, otherwise the provider default."""
    return list(role_args) if role_args is not None else list(provider_default)


def resolve_model_extra_args(
    model: str,
    model_args: dict[str, list[str]],
) -> list[str]:
    """Return model-specific extra args (e.g. --reasoning-effort)
    for the resolved model."""
    return list(model_args.get(model) or [])
