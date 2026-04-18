from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..shared.models import (
    PROMPT_AGENT_ROLES,
    AgentConfig,
    CompletionSettings,
    GitHubConfig,
    WorkflowSettings,
)
from .schema import RawConfigModel

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
    merged = load_builtin_catalog()
    explicit_path = config_path.resolve()
    merged = _deep_merge(merged, _load_structured_file(explicit_path))
    config = _parse_and_validate(merged)
    return _resolve_loaded_config(config, merged, (BUILTIN_CONFIG_PATH, explicit_path))


def load_layered_config(
    project_dir: Path,
    explicit_config_path: Path | None = None,
) -> LoadedConfig:
    """Load config by merging layers in order: default < user < project < explicit.

    Merge semantics for _deep_merge:
    - Dicts: merged recursively (higher-priority layer wins per key)
    - Lists: higher-priority layer replaces base list entirely
    - Scalars: higher-priority layer wins
    - Missing keys in override: base value is preserved
    """
    merged = load_builtin_catalog()
    sources: list[Path] = [BUILTIN_CONFIG_PATH]

    user_path = USER_CONFIG_PATH
    if user_path.exists():
        merged = _deep_merge(merged, _load_structured_file(user_path.resolve()))
        sources.append(user_path.resolve())

    project_config_path = _discover_project_config(project_dir)
    if project_config_path is not None:
        merged = _deep_merge(merged, _load_structured_file(project_config_path))
        sources.append(project_config_path)

    if explicit_config_path is not None:
        explicit_path = explicit_config_path.resolve()
        merged = _deep_merge(merged, _load_structured_file(explicit_path))
        sources.append(explicit_path)

    config = _parse_and_validate(merged)
    return _resolve_loaded_config(config, merged, tuple(sources))


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


def _parse_and_validate(raw: dict[str, Any]) -> RawConfigModel:
    """Validate the fully-merged config dict against the schema."""
    try:
        return RawConfigModel.model_validate(raw)
    except ValidationError as exc:
        messages = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        )
        raise ValueError(f"Invalid configuration: {messages}") from exc


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two config dicts, returning a fully independent copy.

    Merge semantics:
    - Dicts: merged recursively; override keys win, missing keys preserved from base
    - Lists: override list replaces base list entirely (no element-wise merging)
    - Scalars: override value wins
    - Result is a deep copy — mutating it does not affect base or override
    """
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if key not in override and isinstance(value, dict):
            merged[key] = _deep_merge(value, {})
        else:
            merged[key] = value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_loaded_config(
    config: RawConfigModel,
    raw: dict[str, Any],
    sources: tuple[Path, ...],
) -> LoadedConfig:
    d = config.defaults
    g = config.github

    session_name = d.session_name
    default_provider = d.provider
    default_model = d.model
    max_review_iterations = d.max_review_iterations
    github = GitHubConfig(
        base_branch=g.base_branch,
        draft=g.draft,
        branch_prefix=g.branch_prefix,
    )
    workflow_settings = WorkflowSettings(
        completion=CompletionSettings(
            skip_final_approval=d.completion.skip_final_approval,
        ),
    )
    compression_enabled = d.compression.enabled

    agents: dict[str, AgentConfig] = {}
    for role in PROMPT_AGENT_ROLES:
        role_config = config.roles.get(role)

        provider_name = (
            role_config.provider if role_config else None
        ) or default_provider
        provider = config.providers.get(provider_name)
        if provider is None:
            available = ", ".join(sorted(config.providers))
            raise ValueError(
                f"Unknown provider '{provider_name}' for role '{role}'. "
                f"Expected one of: {available}"
            )

        provider_default_model = provider.default_model
        if role_config and role_config.model:
            model = role_config.model
        elif provider_default_model:
            model = provider_default_model
        else:
            model = default_model

        if role_config and role_config.args is not None:
            args = list(role_config.args)
        else:
            args = list(provider.default_role_args) + list(
                provider.role_args.get(role) or []
            )

        agents[role] = AgentConfig(
            role=role,
            cli=provider.command,
            model=model,
            model_flag=provider.model_flag,
            args=args,
            trust_snippet=provider.trust_snippet,
            provider=provider_name,
            batch_command=_build_batch_command_from_provider(provider),
            single_coder=provider.single_coder,
            trust_key=provider.trust_key,
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


def _build_batch_command_from_provider(provider: Any) -> Any:
    """Build a BatchCommand from a ProviderConfig."""
    from ..shared.models import BatchCommand, BatchCommandMode

    # New format: batch_command field
    if provider.batch_command is not None:
        bc = provider.batch_command
        return BatchCommand(verb=bc.verb, mode=bc.mode)

    # Legacy format: batch_subcommand string
    legacy = provider.batch_subcommand
    if legacy is not None:
        verb = str(legacy)
        if verb.startswith("-"):
            mode = BatchCommandMode.FLAG
        elif verb == "exec" and provider.command == "codex":
            mode = BatchCommandMode.STDIN
        else:
            mode = BatchCommandMode.POSITIONAL
        return BatchCommand(verb=verb, mode=mode)

    return None
