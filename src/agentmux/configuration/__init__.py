from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..shared.models import (
    PROMPT_AGENT_ROLES,
    AgentConfig,
    CompletionSettings,
    GitHubConfig,
    WorkflowSettings,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
BUILTIN_CONFIG_PATH = Path(__file__).resolve().parent / "defaults" / "config.yaml"
USER_CONFIG_PATH = Path.home() / ".config" / "agentmux" / "config.yaml"
PROJECT_CONFIG_CANDIDATES = (
    Path(".agentmux/config.yaml"),
    Path(".agentmux/config.yml"),
    Path(".agentmux/config.json"),
)


@dataclass(frozen=True)
class LoadedConfig:
    session_name: str
    max_review_iterations: int
    agents: dict[str, AgentConfig]
    github: GitHubConfig
    raw: dict[str, Any]
    sources: tuple[Path, ...]
    workflow_settings: WorkflowSettings
    compression_enabled: bool = False


def load_builtin_catalog() -> dict[str, Any]:
    return _load_structured_file(BUILTIN_CONFIG_PATH)


def load_explicit_config(config_path: Path) -> LoadedConfig:
    raw = _normalize_config(load_builtin_catalog())
    explicit_path = config_path.resolve()
    merged = _deep_merge(raw, _normalize_config(_load_structured_file(explicit_path)))
    return _resolve_loaded_config(merged, (BUILTIN_CONFIG_PATH, explicit_path))


def load_layered_config(
    project_dir: Path,
    explicit_config_path: Path | None = None,
) -> LoadedConfig:
    merged = _normalize_config(load_builtin_catalog())
    sources: list[Path] = [BUILTIN_CONFIG_PATH]

    user_path = USER_CONFIG_PATH
    if user_path.exists():
        merged = _deep_merge(
            merged,
            _normalize_config(_load_structured_file(user_path.resolve())),
        )
        sources.append(user_path.resolve())

    project_config_path = _discover_project_config(project_dir)
    if project_config_path is not None:
        project_data = _normalize_config(_load_structured_file(project_config_path))
        _validate_project_config(project_data, project_config_path)
        merged = _deep_merge(merged, project_data)
        sources.append(project_config_path)

    if explicit_config_path is not None:
        explicit_path = explicit_config_path.resolve()
        merged = _deep_merge(
            merged,
            _normalize_config(_load_structured_file(explicit_path)),
        )
        sources.append(explicit_path)

    return _resolve_loaded_config(merged, tuple(sources))


def infer_project_dir(feature_dir: Path) -> Path:
    if (
        feature_dir.parent.name == ".sessions"
        and feature_dir.parent.parent.name == ".agentmux"
    ):
        return feature_dir.parent.parent.parent
    return feature_dir.parent


def _discover_project_config(project_dir: Path) -> Path | None:
    for relative in PROJECT_CONFIG_CANDIDATES:
        candidate = (project_dir / relative).resolve()
        if candidate.exists():
            return candidate
    return None


def _load_structured_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Config not found: {path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        raise ValueError(
            f"Unsupported config format for {path}. Expected .json, .yaml, or .yml"
        )

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping at the top level: {path}")
    return data


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    # Check for profile key usage (not supported)
    if "profile" in raw.get("defaults", {}):
        raise ValueError(
            "Profiles are not supported. Use 'model: <model-name>' directly."
        )
    for role in PROMPT_AGENT_ROLES:
        if role in raw.get("roles", {}) and "profile" in raw["roles"][role]:
            raise ValueError(
                "Profiles are not supported. Use 'model: <model-name>' "
                f"directly in roles.{role}."
            )

    normalized: dict[str, Any] = {
        "defaults": _normalize_defaults(raw.get("defaults", {})),
        "github": _normalize_github(raw.get("github", {})),
        "providers": {},
        "roles": {},
    }

    providers = (
        dict(raw.get("providers", {})) if isinstance(raw.get("providers"), dict) else {}
    )

    normalized["providers"] = {
        str(name): _normalize_provider(str(name), provider_raw)
        for name, provider_raw in providers.items()
    }

    nested_roles = (
        dict(raw.get("roles", {})) if isinstance(raw.get("roles"), dict) else {}
    )
    normalized["roles"] = {
        str(role): _normalize_role_config(str(role), role_raw)
        for role, role_raw in nested_roles.items()
    }
    return normalized


def _normalize_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("defaults must be a mapping.")
    unsupported_keys = [
        key
        for key in ("skip_final_approval", "require_final_approval", "tier", "profile")
        if key in raw
    ]
    if unsupported_keys:
        keys_csv = ", ".join(sorted(unsupported_keys))
        raise ValueError(
            "Legacy defaults keys are no longer supported. "
            "Use `defaults.model` and `defaults.completion.skip_final_approval` "
            f"instead: {keys_csv}."
        )
    defaults: dict[str, Any] = {}
    if "session_name" in raw:
        defaults["session_name"] = str(raw["session_name"])
    if "provider" in raw:
        defaults["provider"] = str(raw["provider"])
    if "model" in raw:
        defaults["model"] = str(raw["model"])
    if "max_review_iterations" in raw:
        defaults["max_review_iterations"] = int(raw["max_review_iterations"])
    completion = _normalize_completion_defaults(
        raw.get("completion"), "defaults.completion"
    )
    if completion:
        defaults["completion"] = completion
    if "compression" in raw:
        compression = _normalize_compression_defaults(
            raw["compression"], "defaults.compression"
        )
        if compression:
            defaults["compression"] = compression
    return defaults


def _normalize_completion_defaults(raw: Any, label: str) -> dict[str, bool]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping.")
    completion: dict[str, bool] = {}
    if "skip_final_approval" in raw:
        completion["skip_final_approval"] = _coerce_bool(
            raw["skip_final_approval"],
            f"{label}.skip_final_approval",
        )
    if "require_final_approval" in raw:
        raise ValueError(f"{label}.require_final_approval is no longer supported.")
    return completion


def _normalize_compression_defaults(raw: Any, label: str) -> dict[str, bool]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a mapping.")
    compression: dict[str, bool] = {}
    if "enabled" in raw:
        compression["enabled"] = _coerce_bool(raw["enabled"], f"{label}.enabled")
    return compression


def _normalize_provider(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Provider '{name}' must be a mapping.")
    role_args = raw.get("role_args", {})
    if role_args is None:
        role_args = {}
    if not isinstance(role_args, dict):
        raise ValueError(f"Provider '{name}'.role_args must be a mapping.")

    # Start with required fields
    result: dict[str, Any] = {
        "command": str(raw.get("command", name)),
        "model_flag": raw.get("model_flag"),
        "role_args": {
            str(role): _normalize_args(f"providers.{name}.role_args.{role}", args)
            for role, args in role_args.items()
        },
    }

    # Only add optional fields if they have values
    # (preserves builtin values during merge)
    if raw.get("trust_snippet") is not None:
        result["trust_snippet"] = str(raw["trust_snippet"])
    if raw.get("batch_subcommand") is not None:
        result["batch_subcommand"] = str(raw["batch_subcommand"])
    if raw.get("batch_command") is not None:
        result["batch_command"] = _parse_batch_command_config(raw["batch_command"])
    if raw.get("single_coder") is not None:
        result["single_coder"] = bool(raw["single_coder"])
    if raw.get("default_model") is not None:
        result["default_model"] = str(raw["default_model"])
    if raw.get("default_role_args") is not None:
        result["default_role_args"] = _normalize_args(
            f"providers.{name}.default_role_args", raw["default_role_args"]
        )

    return result


def _parse_batch_command_config(raw: Any) -> dict[str, Any]:
    """Parse batch_command from config, supporting dict and string formats."""
    from ..shared.models import BatchCommandMode

    if isinstance(raw, dict):
        verb = str(raw.get("verb", ""))
        mode_str = str(raw.get("mode", "positional"))
        try:
            mode = BatchCommandMode(mode_str)
        except ValueError as e:
            valid = ", ".join(m.value for m in BatchCommandMode)
            raise ValueError(
                f"Invalid batch_command.mode: '{mode_str}'. Expected one of: {valid}"
            ) from e
        return {"verb": verb, "mode": mode}
    # String fallback: will be converted to BatchCommand in providers.py
    return {"verb": str(raw), "mode": None}


def _build_batch_command_from_provider(provider: dict):
    """Build a BatchCommand from a provider dict, handling both old and new formats."""
    from ..shared.models import BatchCommand, BatchCommandMode

    # New format
    raw_batch = provider.get("batch_command")
    if raw_batch is not None:
        if isinstance(raw_batch, dict):
            verb = str(raw_batch.get("verb", ""))
            mode_raw = raw_batch.get("mode")
            if isinstance(mode_raw, BatchCommandMode):
                return BatchCommand(verb=verb, mode=mode_raw)
            if mode_raw is not None:
                mode = BatchCommandMode(str(mode_raw))
            else:
                # Infer from verb
                if verb.startswith("-"):
                    mode = BatchCommandMode.FLAG
                elif verb == "exec" and provider.get("command") == "codex":
                    mode = BatchCommandMode.STDIN
                else:
                    mode = BatchCommandMode.POSITIONAL
            return BatchCommand(verb=verb, mode=mode)
        # String
        verb = str(raw_batch)
        if verb.startswith("-"):
            mode = BatchCommandMode.FLAG
        elif verb == "exec" and provider.get("command") == "codex":
            mode = BatchCommandMode.STDIN
        else:
            mode = BatchCommandMode.POSITIONAL
        return BatchCommand(verb=verb, mode=mode)

    # Legacy format
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


def _normalize_role_config(role: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Role '{role}' must be a mapping.")
    if "tier" in raw:
        raise ValueError(
            f"roles.{role}.tier is no longer supported. Use roles.{role}.model."
        )
    if "profile" in raw:
        raise ValueError(
            f"roles.{role}.profile is no longer supported. "
            f"Use roles.{role}.model: <model-name>."
        )
    data: dict[str, Any] = {}
    if "provider" in raw:
        data["provider"] = str(raw["provider"])
    if "model" in raw:
        data["model"] = str(raw["model"])
    if "args" in raw:
        data["args"] = _normalize_args(f"roles.{role}.args", raw["args"])
    return data


def _normalize_args(label: str, raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list of strings.")
    return [str(item) for item in raw]


def _coerce_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"{label} must be a boolean.")


def _normalize_github(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("github must be a mapping.")
    data: dict[str, Any] = {}
    if "base_branch" in raw:
        data["base_branch"] = str(raw["base_branch"])
    if "draft" in raw:
        data["draft"] = _coerce_bool(raw["draft"], "github.draft")
    if "branch_prefix" in raw:
        data["branch_prefix"] = str(raw["branch_prefix"])
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_project_config(raw: dict[str, Any], path: Path) -> None:
    # In v2, project configs CAN define providers (removed restriction)
    # We just validate that the structure is valid
    pass


def _resolve_loaded_config(
    raw: dict[str, Any], sources: tuple[Path, ...]
) -> LoadedConfig:
    defaults = raw.get("defaults", {})
    github_raw = raw.get("github", {})
    providers = raw.get("providers", {})
    roles = raw.get("roles", {})

    session_name = str(defaults.get("session_name", "multi-agent-mvp"))
    default_provider = str(defaults.get("provider", "claude"))
    default_model = str(defaults.get("model", "sonnet"))
    max_review_iterations = int(defaults.get("max_review_iterations", 3))
    github = GitHubConfig(
        base_branch=str(github_raw.get("base_branch", "main")),
        draft=_coerce_bool(github_raw.get("draft", True), "github.draft"),
        branch_prefix=str(github_raw.get("branch_prefix", "feature/")),
    )
    completion_defaults = _normalize_completion_defaults(
        defaults.get("completion"), "defaults.completion"
    )
    workflow_settings = WorkflowSettings(
        completion=CompletionSettings(
            skip_final_approval=completion_defaults.get("skip_final_approval", False),
        ),
    )
    compression_defaults = _normalize_compression_defaults(
        defaults.get("compression"), "defaults.compression"
    )
    compression_enabled = bool(compression_defaults.get("enabled", False))

    agents: dict[str, AgentConfig] = {}
    for role in PROMPT_AGENT_ROLES:
        role_config = roles.get(role) or {}

        provider_name = str(role_config.get("provider", default_provider))
        try:
            provider = providers[provider_name]
        except KeyError as exc:
            available = ", ".join(sorted(providers))
            raise ValueError(
                f"Unknown provider '{provider_name}' for role '{role}'. "
                f"Expected one of: {available}"
            ) from exc

        # In v2, model is specified directly in role config or defaults
        # Use provider default_model as fallback if available
        provider_default_model = provider.get("default_model")
        if provider_default_model:
            model = str(role_config.get("model", provider_default_model))
        else:
            model = str(role_config.get("model", default_model))

        args = role_config.get("args")
        if args is None:
            # Merge default_role_args with role-specific args
            default_role_args = provider.get("default_role_args", [])
            role_specific_args = provider.get("role_args", {}).get(role, [])
            args = list(default_role_args) + list(role_specific_args)

        agents[role] = AgentConfig(
            role=role,
            cli=str(provider.get("command", provider_name)),
            model=model,
            model_flag=provider.get("model_flag"),
            args=list(args),
            trust_snippet=provider.get("trust_snippet"),
            provider=provider_name,
            batch_command=_build_batch_command_from_provider(provider),
            single_coder=bool(provider.get("single_coder", False)),
        )

    return LoadedConfig(
        session_name=session_name,
        max_review_iterations=max_review_iterations,
        agents=agents,
        github=github,
        workflow_settings=workflow_settings,
        compression_enabled=compression_enabled,
        raw=raw,
        sources=sources,
    )
