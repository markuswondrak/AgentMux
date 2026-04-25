"""Pydantic v2 schema for agentmux YAML configuration.

Used to validate the fully-merged config dict before resolving AgentConfig objects.
Each layer (default, user, project, explicit) is loaded as a raw dict and deep-merged
first; model_validate() is called exactly once on the merged result.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..shared.models import BatchCommandMode


class BatchCommandConfig(BaseModel):
    verb: str = ""
    mode: BatchCommandMode = BatchCommandMode.POSITIONAL

    @field_validator("mode", mode="before")
    @classmethod
    def coerce_mode(cls, v: Any) -> BatchCommandMode:
        if isinstance(v, BatchCommandMode):
            return v
        try:
            return BatchCommandMode(str(v))
        except ValueError as exc:
            valid = ", ".join(m.value for m in BatchCommandMode)
            raise ValueError(
                f"Invalid batch_command.mode '{v}'. Expected one of: {valid}"
            ) from exc


class ProviderConfig(BaseModel):
    command: str
    model_flag: str | None = None
    trust_snippet: str | None = None
    trust_key: str = "Enter"
    sub_agent_tool: str | None = None
    role_args: dict[str, list[str]] = Field(default_factory=dict)
    default_role_args: list[str] = Field(default_factory=list)
    batch_command: BatchCommandConfig | None = None
    batch_subcommand: str | None = None
    single_coder: bool = False
    default_model: str | None = None
    model_args: dict[str, list[str]] = Field(default_factory=dict)


class CompletionConfig(BaseModel):
    skip_final_approval: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_keys(cls, v: Any) -> Any:
        if isinstance(v, dict) and "require_final_approval" in v:
            raise ValueError(
                "defaults.completion.require_final_approval is no longer supported."
            )
        return v


class CompressionConfig(BaseModel):
    enabled: bool = False


_LEGACY_DEFAULTS_KEYS = {
    "skip_final_approval",
    "require_final_approval",
    "tier",
    "profile",
}


class DefaultsConfig(BaseModel):
    session_name: str = "multi-agent-mvp"
    provider: str = "claude"
    model: str | None = None
    max_review_iterations: int = 3
    completion: CompletionConfig = Field(default_factory=CompletionConfig)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_keys(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        found = sorted(_LEGACY_DEFAULTS_KEYS & v.keys())
        if found:
            keys_csv = ", ".join(found)
            raise ValueError(
                "Legacy defaults keys are no longer supported. "
                "Use `defaults.model` and `defaults.completion.skip_final_approval` "
                f"instead: {keys_csv}."
            )
        return v


class GitHubConfig(BaseModel):
    base_branch: str = "main"
    draft: bool = True
    branch_prefix: str = "feature/"


class RoleConfig(BaseModel):
    provider: str | None = None
    model: str | None = None
    args: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_keys(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        if "tier" in v:
            raise ValueError(
                "roles.<role>.tier is no longer supported. Use roles.<role>.model."
            )
        if "profile" in v:
            raise ValueError(
                "roles.<role>.profile is no longer supported. "
                "Use roles.<role>.model: <model-name>."
            )
        return v


class RawConfigModel(BaseModel):
    version: Annotated[int, Field(ge=1)] = 2
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def reject_profile_in_roles(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        for role_name, role_raw in (v.get("roles") or {}).items():
            if isinstance(role_raw, dict) and "profile" in role_raw:
                raise ValueError(
                    f"Profiles are not supported. Use 'model: <model-name>' "
                    f"directly in roles.{role_name}."
                )
        return v
