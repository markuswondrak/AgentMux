"""Unit tests for configuration._resolve — canonical attribute resolution helpers."""

from __future__ import annotations

import pytest

from agentmux.configuration._resolve import (
    resolve_args,
    resolve_model,
    resolve_model_extra_args,
)


class TestResolveModel:
    """Priority: role > global_default > provider_default > 'sonnet' fallback."""

    def test_role_wins_over_all(self) -> None:
        assert resolve_model("role-m", "global-m", "provider-m") == "role-m"

    def test_global_default_wins_over_provider(self) -> None:
        assert resolve_model(None, "global-m", "provider-m") == "global-m"

    def test_provider_default_wins_over_fallback(self) -> None:
        assert resolve_model(None, None, "provider-m") == "provider-m"

    def test_sonnet_fallback_when_all_none(self) -> None:
        assert resolve_model(None, None, None) == "sonnet"

    def test_only_role_set(self) -> None:
        assert resolve_model("role-m", None, None) == "role-m"

    def test_only_global_set(self) -> None:
        assert resolve_model(None, "global-m", None) == "global-m"

    def test_real_world_copilot_user_sets_opus(self) -> None:
        """Regression: defaults.model must override provider.default_model."""
        model = resolve_model(
            role_model=None,
            global_default="claude-opus-4.6",
            provider_default="claude-sonnet-4.6",
        )
        assert model == "claude-opus-4.6"

    def test_real_world_copilot_no_user_model(self) -> None:
        """When user doesn't set defaults.model, provider default applies."""
        model = resolve_model(
            role_model=None,
            global_default=None,
            provider_default="claude-sonnet-4.6",
        )
        assert model == "claude-sonnet-4.6"

    def test_role_overrides_everything(self) -> None:
        model = resolve_model(
            role_model="claude-haiku-4.5",
            global_default="claude-opus-4.6",
            provider_default="claude-sonnet-4.6",
        )
        assert model == "claude-haiku-4.5"


class TestResolveArgs:
    """Role args win if explicitly set; otherwise provider default is used."""

    def test_role_args_used_when_set(self) -> None:
        assert resolve_args(["--custom"], ["--default"]) == ["--custom"]

    def test_provider_default_used_when_role_args_none(self) -> None:
        assert resolve_args(None, ["--default"]) == ["--default"]

    def test_empty_role_args_list_wins_over_provider_default(self) -> None:
        """Empty list is an explicit override (not the same as None)."""
        assert resolve_args([], ["--default"]) == []

    def test_returns_copy_not_same_reference(self) -> None:
        provider_default = ["--a"]
        result = resolve_args(None, provider_default)
        result.append("--b")
        assert provider_default == ["--a"]

    def test_role_args_copy_not_same_reference(self) -> None:
        role_args = ["--x"]
        result = resolve_args(role_args, ["--y"])
        result.append("--z")
        assert role_args == ["--x"]


class TestResolveModelExtraArgs:
    """Model-specific extra args looked up from model_args dict."""

    def test_returns_extra_args_for_known_model(self) -> None:
        model_args = {"claude-opus-4.6": ["--reasoning-effort", "high"]}
        assert resolve_model_extra_args("claude-opus-4.6", model_args) == [
            "--reasoning-effort",
            "high",
        ]

    def test_returns_empty_for_unknown_model(self) -> None:
        model_args = {"claude-opus-4.6": ["--reasoning-effort", "high"]}
        assert resolve_model_extra_args("claude-haiku-4.5", model_args) == []

    def test_returns_empty_for_empty_map(self) -> None:
        assert resolve_model_extra_args("any-model", {}) == []

    def test_returns_copy_not_same_reference(self) -> None:
        extra = ["--reasoning-effort", "high"]
        model_args = {"m": extra}
        result = resolve_model_extra_args("m", model_args)
        result.append("--extra")
        assert extra == ["--reasoning-effort", "high"]


@pytest.mark.parametrize(
    "role_model,global_default,provider_default,expected",
    [
        ("role", "global", "provider", "role"),
        (None, "global", "provider", "global"),
        (None, None, "provider", "provider"),
        (None, None, None, "sonnet"),
    ],
)
def test_resolve_model_parametrized(
    role_model: str | None,
    global_default: str | None,
    provider_default: str | None,
    expected: str,
) -> None:
    assert resolve_model(role_model, global_default, provider_default) == expected
