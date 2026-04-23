"""Tests for Pydantic schema validation in agentmux.configuration.schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentmux.configuration.schema import (
    BatchCommandConfig,
    DefaultsConfig,
    ProviderConfig,
    RawConfigModel,
    RoleConfig,
)
from agentmux.shared.models import BatchCommandMode


class TestBatchCommandConfig:
    def test_valid_mode_string(self) -> None:
        bc = BatchCommandConfig(verb="-p", mode="flag")  # type: ignore[arg-type]
        assert bc.mode == BatchCommandMode.FLAG

    def test_valid_mode_enum(self) -> None:
        bc = BatchCommandConfig(verb="run", mode=BatchCommandMode.POSITIONAL)
        assert bc.mode == BatchCommandMode.POSITIONAL

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid batch_command.mode"):
            BatchCommandConfig(verb="run", mode="unknown")  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        bc = BatchCommandConfig()
        assert bc.verb == ""
        assert bc.mode == BatchCommandMode.POSITIONAL


class TestProviderConfig:
    def test_minimal_provider(self) -> None:
        p = ProviderConfig(command="mycli")
        assert p.command == "mycli"
        assert p.model_flag is None
        assert p.trust_snippet is None
        assert p.trust_key == "Enter"
        assert p.role_args == {}
        assert p.default_role_args == []
        assert p.batch_command is None
        assert p.batch_subcommand is None
        assert p.single_coder is False
        assert p.default_model is None

    def test_explicit_null_model_flag(self) -> None:
        p = ProviderConfig(command="mycli", model_flag=None)
        assert p.model_flag is None

    def test_batch_command_nested(self) -> None:
        p = ProviderConfig(
            command="agent",
            batch_command={"verb": "-p", "mode": "flag"},
        )
        assert p.batch_command is not None
        assert p.batch_command.verb == "-p"
        assert p.batch_command.mode == BatchCommandMode.FLAG

    def test_role_args_preserved(self) -> None:
        p = ProviderConfig(command="cli", role_args={"coder": ["--sandbox", "write"]})
        assert p.role_args["coder"] == ["--sandbox", "write"]


class TestDefaultsConfig:
    def test_valid_defaults(self) -> None:
        d = DefaultsConfig(provider="claude", model="opus")
        assert d.provider == "claude"
        assert d.model == "opus"
        assert d.max_review_iterations == 3

    def test_legacy_key_profile_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="Legacy defaults keys are no longer supported"
        ):
            DefaultsConfig.model_validate({"profile": "max"})

    def test_legacy_key_tier_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="Legacy defaults keys are no longer supported"
        ):
            DefaultsConfig.model_validate({"tier": "premium"})

    def test_legacy_key_skip_final_approval_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="Legacy defaults keys are no longer supported"
        ):
            DefaultsConfig.model_validate({"skip_final_approval": True})

    def test_completion_nested(self) -> None:
        d = DefaultsConfig.model_validate({"completion": {"skip_final_approval": True}})
        assert d.completion.skip_final_approval is True

    def test_compression_nested(self) -> None:
        d = DefaultsConfig.model_validate({"compression": {"enabled": True}})
        assert d.compression.enabled is True


class TestRoleConfig:
    def test_empty_role_config(self) -> None:
        r = RoleConfig()
        assert r.provider is None
        assert r.model is None
        assert r.args is None

    def test_full_role_config(self) -> None:
        r = RoleConfig(provider="claude", model="opus", args=["--flag"])
        assert r.provider == "claude"
        assert r.model == "opus"
        assert r.args == ["--flag"]

    def test_legacy_tier_raises(self) -> None:
        with pytest.raises(ValidationError, match="tier is no longer supported"):
            RoleConfig.model_validate({"tier": "pro"})

    def test_legacy_profile_raises(self) -> None:
        with pytest.raises(ValidationError, match="profile is no longer supported"):
            RoleConfig.model_validate({"profile": "max"})


class TestRawConfigModel:
    def test_minimal_valid(self) -> None:
        m = RawConfigModel.model_validate({})
        assert m.version == 2
        assert m.providers == {}
        assert m.roles == {}

    def test_version_field(self) -> None:
        m = RawConfigModel.model_validate({"version": 2})
        assert m.version == 2

    def test_profile_in_roles_raises(self) -> None:
        with pytest.raises(ValidationError, match="Profiles are not supported"):
            RawConfigModel.model_validate(
                {
                    "roles": {
                        "coder": {"profile": "max"},
                    }
                }
            )

    def test_providers_parsed(self) -> None:
        m = RawConfigModel.model_validate(
            {
                "providers": {
                    "mycli": {
                        "command": "mycli",
                        "model_flag": "--model-name",
                    }
                }
            }
        )
        assert "mycli" in m.providers
        assert m.providers["mycli"].command == "mycli"
        assert m.providers["mycli"].model_flag == "--model-name"

    def test_roles_parsed(self) -> None:
        m = RawConfigModel.model_validate(
            {
                "roles": {
                    "coder": {"provider": "claude", "model": "opus"},
                }
            }
        )
        assert m.roles["coder"].provider == "claude"
        assert m.roles["coder"].model == "opus"

    def test_legacy_defaults_key_raises(self) -> None:
        with pytest.raises(
            ValidationError, match="Legacy defaults keys are no longer supported"
        ):
            RawConfigModel.model_validate({"defaults": {"profile": "max"}})

    def test_full_builtin_config_is_valid(self) -> None:
        """The built-in config.yaml must validate without errors."""
        from pathlib import Path

        import yaml

        builtin = (
            Path(__file__).parent.parent
            / "src"
            / "agentmux"
            / "configuration"
            / "defaults"
            / "config.yaml"
        )
        raw = yaml.safe_load(builtin.read_text(encoding="utf-8"))
        m = RawConfigModel.model_validate(raw)
        assert "claude" in m.providers
        assert "cursor" in m.providers
        assert m.providers["cursor"].trust_key == "a"
