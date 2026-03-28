from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml

from ..shared.models import AgentConfig, CompletionSettings, GitHubConfig, WorkflowSettings

ROLES = (
    "architect",
    "product-manager",
    "reviewer",
    "coder",
    "designer",
    "code-researcher",
    "web-researcher",
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
    if feature_dir.parent.name == ".sessions" and feature_dir.parent.parent.name == ".agentmux":
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
        raise ValueError(f"Unsupported config format for {path}. Expected .json, .yaml, or .yml")

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a mapping at the top level: {path}")
    return data


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    legacy_top_level_keys = {
        "session_name",
        "provider",
        "profile",
        "max_review_iterations",
        "skip_final_approval",
        "require_final_approval",
        *ROLES,
    }
    found_legacy_keys = sorted(key for key in legacy_top_level_keys if key in raw)
    if found_legacy_keys:
        found_csv = ", ".join(found_legacy_keys)
        raise ValueError(
            "Legacy top-level config keys are no longer supported. "
            f"Move them under `defaults`/`roles`: {found_csv}."
        )

    normalized: dict[str, Any] = {
        "version": int(raw.get("version", 1)),
        "defaults": _normalize_defaults(raw.get("defaults", {})),
        "github": _normalize_github(raw.get("github", {})),
        "launchers": {},
        "profiles": {},
        "roles": {},
    }

    launchers = dict(raw.get("launchers", {})) if isinstance(raw.get("launchers"), dict) else {}
    normalized["launchers"] = {
        str(name): _normalize_launcher(str(name), launcher_raw)
        for name, launcher_raw in launchers.items()
    }

    profiles = dict(raw.get("profiles", {})) if isinstance(raw.get("profiles"), dict) else {}
    normalized["profiles"] = {
        str(provider): _normalize_profile_map(str(provider), profile_map)
        for provider, profile_map in profiles.items()
    }

    nested_roles = dict(raw.get("roles", {})) if isinstance(raw.get("roles"), dict) else {}
    normalized["roles"] = {
        str(role): _normalize_role_config(str(role), role_raw)
        for role, role_raw in nested_roles.items()
    }
    return normalized


def _normalize_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("defaults must be a mapping.")
    unsupported_keys = [key for key in ("skip_final_approval", "require_final_approval", "tier") if key in raw]
    if unsupported_keys:
        keys_csv = ", ".join(sorted(unsupported_keys))
        raise ValueError(
            "Legacy defaults keys are no longer supported. "
            f"Use `defaults.profile` and `defaults.completion.skip_final_approval` instead: {keys_csv}."
        )
    defaults: dict[str, Any] = {}
    if "session_name" in raw:
        defaults["session_name"] = str(raw["session_name"])
    if "provider" in raw:
        defaults["provider"] = str(raw["provider"])
    profile = raw.get("profile")
    if profile is not None:
        defaults["profile"] = str(profile)
    if "max_review_iterations" in raw:
        defaults["max_review_iterations"] = int(raw["max_review_iterations"])
    completion = _normalize_completion_defaults(raw.get("completion"), "defaults.completion")
    if completion:
        defaults["completion"] = completion
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


def _normalize_launcher(name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Launcher '{name}' must be a mapping.")
    role_args = raw.get("role_args", {})
    if role_args is None:
        role_args = {}
    if not isinstance(role_args, dict):
        raise ValueError(f"Launcher '{name}'.role_args must be a mapping.")
    return {
        "command": str(raw.get("command", name)),
        "model_flag": str(raw.get("model_flag", "--model")),
        "trust_snippet": None if raw.get("trust_snippet") is None else str(raw["trust_snippet"]),
        "role_args": {
            str(role): _normalize_args(f"launchers.{name}.role_args.{role}", args)
            for role, args in role_args.items()
        },
    }


def _normalize_profile_map(provider: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Profiles for provider '{provider}' must be a mapping.")
    return {
        str(profile): _normalize_profile(provider, str(profile), profile_raw)
        for profile, profile_raw in raw.items()
    }


def _normalize_profile(provider: str, profile: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Profile '{provider}.{profile}' must be a mapping.")
    if "model" not in raw:
        raise ValueError(f"Profile '{provider}.{profile}' must define 'model'.")
    data = {"model": str(raw["model"])}
    if "args" in raw:
        data["args"] = _normalize_args(f"profiles.{provider}.{profile}.args", raw["args"])
    return data


def _normalize_role_config(role: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Role '{role}' must be a mapping.")
    if "tier" in raw:
        raise ValueError(f"roles.{role}.tier is no longer supported. Use roles.{role}.profile.")
    data: dict[str, Any] = {}
    if "provider" in raw:
        data["provider"] = str(raw["provider"])
    profile = raw.get("profile")
    if profile is not None:
        data["profile"] = str(profile)
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
    if isinstance(value, int):
        if value in {0, 1}:
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
    if raw.get("launchers"):
        raise ValueError(
            f"Project config may not define launchers: {path}. "
            "Define custom launchers in user config (~/.config/agentmux/config.yaml) or an explicit --config file."
        )
    if raw.get("profiles"):
        raise ValueError(
            f"Project config may not define profiles: {path}. "
            "Define custom profiles in user config (~/.config/agentmux/config.yaml) or an explicit --config file."
        )


def _resolve_loaded_config(raw: dict[str, Any], sources: tuple[Path, ...]) -> LoadedConfig:
    defaults = raw.get("defaults", {})
    github_raw = raw.get("github", {})
    launchers = raw.get("launchers", {})
    profiles = raw.get("profiles", {})
    roles = raw.get("roles", {})

    session_name = str(defaults.get("session_name", "multi-agent-mvp"))
    default_provider = str(defaults.get("provider", "claude"))
    default_profile = str(defaults.get("profile", "standard"))
    max_review_iterations = int(defaults.get("max_review_iterations", 3))
    github = GitHubConfig(
        base_branch=str(github_raw.get("base_branch", "main")),
        draft=_coerce_bool(github_raw.get("draft", True), "github.draft"),
        branch_prefix=str(github_raw.get("branch_prefix", "feature/")),
    )
    completion_defaults = _normalize_completion_defaults(defaults.get("completion"), "defaults.completion")
    workflow_settings = WorkflowSettings(
        completion=CompletionSettings(
            skip_final_approval=completion_defaults.get("skip_final_approval", False),
        ),
    )

    agents: dict[str, AgentConfig] = {}
    for role in ROLES:
        role_config = roles.get(role)
        if not role_config:
            continue

        provider_name = str(role_config.get("provider", default_provider))
        try:
            launcher = launchers[provider_name]
        except KeyError as exc:
            available = ", ".join(sorted(launchers))
            raise ValueError(
                f"Unknown provider '{provider_name}' for role '{role}'. Expected one of: {available}"
            ) from exc

        try:
            provider_profiles = profiles[provider_name]
        except KeyError as exc:
            raise ValueError(f"No profiles configured for provider '{provider_name}'.") from exc

        profile_name = str(role_config.get("profile", default_profile))
        try:
            profile = provider_profiles[profile_name]
        except KeyError as exc:
            valid_profiles = ", ".join(sorted(provider_profiles))
            raise ValueError(
                f"Unknown profile '{profile_name}' for provider '{provider_name}'. "
                f"Expected one of: {valid_profiles}"
            ) from exc

        args = role_config.get("args")
        if args is None:
            args = list(launcher.get("role_args", {}).get(role, []))
            args.extend(profile.get("args", []))

        agents[role] = AgentConfig(
            role=role,
            cli=str(launcher.get("command", provider_name)),
            model=str(profile["model"]),
            model_flag=str(launcher.get("model_flag", "--model")),
            args=list(args),
            trust_snippet=launcher.get("trust_snippet"),
            provider=provider_name,
        )

    return LoadedConfig(
        session_name=session_name,
        max_review_iterations=max_review_iterations,
        agents=agents,
        github=github,
        workflow_settings=workflow_settings,
        raw=raw,
        sources=sources,
    )
