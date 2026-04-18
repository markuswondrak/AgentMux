"""Tests for config merge behavior.

Covers two levels:
1. _deep_merge unit tests — the raw merge primitive
2. load_layered_config integration tests — full layer priority
   (default < user < project < explicit)
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from agentmux.configuration import _deep_merge, load_layered_config

# ---------------------------------------------------------------------------
# Part 1: _deep_merge unit tests
# ---------------------------------------------------------------------------

_NO_USER = "agentmux.configuration.USER_CONFIG_PATH"


class TestDeepMergeScalars:
    def test_scalar_override_wins(self) -> None:
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_missing_key_preserved_from_base(self) -> None:
        result = _deep_merge({"a": 1, "b": 2}, {"a": 9})
        assert result == {"a": 9, "b": 2}

    def test_new_key_from_override_added(self) -> None:
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_empty_override_leaves_base_unchanged(self) -> None:
        assert _deep_merge({"a": 1}, {}) == {"a": 1}

    def test_empty_base_with_override(self) -> None:
        assert _deep_merge({}, {"a": 1}) == {"a": 1}

    def test_both_empty(self) -> None:
        assert _deep_merge({}, {}) == {}

    def test_string_scalar_override(self) -> None:
        result = _deep_merge({"key": "base"}, {"key": "override"})
        assert result == {"key": "override"}

    def test_none_override_replaces_scalar(self) -> None:
        assert _deep_merge({"key": "base"}, {"key": None}) == {"key": None}


class TestDeepMergeNested:
    def test_nested_dict_merged_recursively(self) -> None:
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"a": 9}}
        assert _deep_merge(base, override) == {"x": {"a": 9, "b": 2}}

    def test_nested_missing_key_preserved(self) -> None:
        base = {"x": {"a": 1, "b": 2, "c": 3}}
        override = {"x": {"b": 99}}
        result = _deep_merge(base, override)
        assert result["x"] == {"a": 1, "b": 99, "c": 3}

    def test_three_levels_deep(self) -> None:
        """Mirrors providers.<name>.role_args structure."""
        base = {
            "providers": {
                "claude": {
                    "role_args": {
                        "coder": ["--flag-coder"],
                        "architect": ["--flag-arch"],
                    }
                }
            }
        }
        override = {
            "providers": {
                "claude": {
                    "role_args": {
                        "coder": ["--new-flag"],
                    }
                }
            }
        }
        result = _deep_merge(base, override)
        role_args = result["providers"]["claude"]["role_args"]
        # coder is overridden (list replace semantics)
        assert role_args["coder"] == ["--new-flag"]
        # architect is untouched
        assert role_args["architect"] == ["--flag-arch"]

    def test_override_none_replaces_dict(self) -> None:
        """None in override must replace a dict, not be skipped."""
        base = {"x": {"a": 1}}
        override = {"x": None}
        result = _deep_merge(base, override)
        assert result["x"] is None

    def test_new_nested_key_added(self) -> None:
        base = {"x": {"a": 1}}
        override = {"x": {"b": 2}}
        assert _deep_merge(base, override) == {"x": {"a": 1, "b": 2}}

    def test_top_level_new_nested_dict_added(self) -> None:
        base = {"a": 1}
        override = {"nested": {"b": 2}}
        assert _deep_merge(base, override) == {"a": 1, "nested": {"b": 2}}


class TestDeepMergeLists:
    def test_list_replaced_entirely(self) -> None:
        result = _deep_merge({"args": [1, 2, 3]}, {"args": [9]})
        assert result == {"args": [9]}

    def test_empty_list_in_override_replaces(self) -> None:
        assert _deep_merge({"args": [1, 2]}, {"args": []}) == {"args": []}

    def test_list_in_base_preserved_when_not_in_override(self) -> None:
        result = _deep_merge({"args": [1, 2], "other": "x"}, {"other": "y"})
        assert result["args"] == [1, 2]

    def test_list_not_extended_only_replaced(self) -> None:
        base = {"args": ["--a", "--b"]}
        override = {"args": ["--c"]}
        result = _deep_merge(base, override)
        assert result["args"] == ["--c"]
        assert "--a" not in result["args"]


class TestDeepMergeImmutability:
    def test_base_dict_not_mutated(self) -> None:
        base = {"a": 1, "nested": {"b": 2}}
        override = {"a": 9, "nested": {"b": 99, "c": 3}}
        _deep_merge(base, override)
        assert base == {"a": 1, "nested": {"b": 2}}

    def test_override_dict_not_mutated(self) -> None:
        base = {"a": 1}
        override = {"b": 2}
        _deep_merge(base, override)
        assert override == {"b": 2}

    def test_result_is_independent_copy(self) -> None:
        """Mutating a nested dict in the result must not affect the base."""
        base = {"nested": {"a": 1}}
        result = _deep_merge(base, {})
        result["nested"]["a"] = 99
        assert base["nested"]["a"] == 1


class TestDeepMergeOrdering:
    def test_order_matters_abc_vs_acb(self) -> None:
        """A + B + C differs from A + C + B when B and C conflict."""
        a = {"x": 1}
        b = {"x": 2}
        c = {"x": 3}
        abc = _deep_merge(_deep_merge(a, b), c)
        acb = _deep_merge(_deep_merge(a, c), b)
        assert abc == {"x": 3}  # c wins in A+B+C
        assert acb == {"x": 2}  # b wins in A+C+B

    def test_three_layer_chain(self) -> None:
        default = {"model": "sonnet", "provider": "claude"}
        user = {"model": "opus"}
        project = {"provider": "codex"}
        result = _deep_merge(_deep_merge(default, user), project)
        assert result == {"model": "opus", "provider": "codex"}


# ---------------------------------------------------------------------------
# Part 2: load_layered_config layer-priority integration tests
# ---------------------------------------------------------------------------


def _write_project_config(project_dir: Path, data: dict) -> None:
    config_dir = project_dir / ".agentmux"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(yaml.dump(data), encoding="utf-8")


def _write_user_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data), encoding="utf-8")


class TestLayeredConfigDefaults:
    def test_builtin_defaults_when_no_overrides(self) -> None:
        """Without any user/project config, built-in defaults apply."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].provider == "claude"
        assert loaded.agents["coder"].model == "sonnet"
        assert loaded.agents["coder"].cli == "claude"

    def test_builtin_cursor_trust_key_preserved(self) -> None:
        """Built-in cursor provider has trust_key='a' — survives with no overrides."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "defaults": {"provider": "cursor"}},
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].trust_key == "a"

    def test_builtin_cursor_trust_snippet_matches_mcp_approval_text(self) -> None:
        """Built-in cursor trust_snippet must match '[a] Approve all servers' modal."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "defaults": {"provider": "cursor"}},
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        snippet = loaded.agents["coder"].trust_snippet
        assert snippet is not None, "Cursor must have a trust_snippet"
        assert "Approve all servers" in snippet, (
            f"trust_snippet {snippet!r} must match Cursor MCP approval modal text"
        )


class TestLayeredConfigUserLayer:
    def test_user_overrides_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            user_config_path = Path(td) / "user-config.yaml"
            _write_user_config(
                user_config_path,
                {"version": 2, "defaults": {"model": "opus"}},
            )
            with patch(_NO_USER, user_config_path):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].model == "opus"
        assert loaded.agents["architect"].model == "opus"

    def test_user_overrides_default_provider(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            user_config_path = Path(td) / "user-config.yaml"
            _write_user_config(
                user_config_path,
                {
                    "version": 2,
                    "defaults": {"provider": "gemini", "model": "gemini-2.5-pro"},
                },
            )
            with patch(_NO_USER, user_config_path):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].cli == "gemini"

    def test_user_partial_override_preserves_unset_defaults(self) -> None:
        """User sets only model; provider must still be the built-in default."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            user_config_path = Path(td) / "user-config.yaml"
            _write_user_config(
                user_config_path,
                {"version": 2, "defaults": {"model": "opus"}},
            )
            with patch(_NO_USER, user_config_path):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].provider == "claude"


class TestLayeredConfigProjectLayer:
    def test_project_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "defaults": {"provider": "codex", "model": "gpt-5"}},
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].cli == "codex"
        assert loaded.agents["coder"].model == "gpt-5"

    def test_project_overrides_user(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            user_config_path = Path(td) / "user-config.yaml"
            _write_user_config(
                user_config_path,
                {"version": 2, "defaults": {"model": "opus"}},
            )
            _write_project_config(
                project_dir,
                {"version": 2, "defaults": {"model": "haiku"}},
            )
            with patch(_NO_USER, user_config_path):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].model == "haiku"

    def test_project_github_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "github": {"base_branch": "develop", "draft": False}},
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.github.base_branch == "develop"
        assert loaded.github.draft is False

    def test_project_unset_github_field_preserved_from_default(self) -> None:
        """Project sets base_branch only; branch_prefix stays as built-in default."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "github": {"base_branch": "develop"}},
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.github.branch_prefix == "feature/"


class TestLayeredConfigExplicitLayer:
    def test_explicit_overrides_project(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "defaults": {"model": "haiku"}},
            )
            explicit_path = Path(td) / "explicit.yaml"
            explicit_path.write_text(
                yaml.dump({"version": 2, "defaults": {"model": "sonnet-3-7"}}),
                encoding="utf-8",
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(
                    project_dir, explicit_config_path=explicit_path
                )
        assert loaded.agents["coder"].model == "sonnet-3-7"

    def test_explicit_overrides_user_and_project(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            user_config_path = Path(td) / "user-config.yaml"
            _write_user_config(
                user_config_path, {"version": 2, "defaults": {"model": "opus"}}
            )
            _write_project_config(
                project_dir, {"version": 2, "defaults": {"model": "haiku"}}
            )
            explicit_path = Path(td) / "explicit.yaml"
            explicit_path.write_text(
                yaml.dump({"version": 2, "defaults": {"model": "explicit-model"}}),
                encoding="utf-8",
            )
            with patch(_NO_USER, user_config_path):
                loaded = load_layered_config(
                    project_dir, explicit_config_path=explicit_path
                )
        assert loaded.agents["coder"].model == "explicit-model"


class TestLayeredConfigProviderFieldMerge:
    def test_partial_provider_override_preserves_builtin_fields(self) -> None:
        """Critical regression: project overrides only cursor.command,
        trust_key must still come from built-in ('a'), not reset to 'Enter'."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {
                    "version": 2,
                    "defaults": {"provider": "cursor"},
                    "providers": {
                        "cursor": {"command": "custom-agent"},
                    },
                },
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].cli == "custom-agent"
        assert loaded.agents["coder"].trust_key == "a"

    def test_role_args_list_replaced_not_extended(self) -> None:
        """Project sets role_args.coder — built-in list must be fully replaced."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {
                    "version": 2,
                    "providers": {
                        "claude": {
                            "role_args": {
                                "coder": ["--my-flag"],
                            }
                        }
                    },
                },
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].args == ["--my-flag"]
        assert "--permission-mode" not in loaded.agents["coder"].args

    def test_unrelated_provider_fields_preserved_when_project_sets_only_model(
        self,
    ) -> None:
        """Project sets defaults.model only; claude provider fields stay as built-in."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {"version": 2, "defaults": {"model": "opus"}},
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert (
            loaded.agents["coder"].trust_snippet
            == "Do you trust the contents of this directory?"
        )
        assert loaded.agents["coder"].model == "opus"

    def test_role_args_other_roles_preserved_when_only_one_overridden(self) -> None:
        """Project overrides coder role_args only; architect args come from built-in."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_project_config(
                project_dir,
                {
                    "version": 2,
                    "providers": {
                        "claude": {
                            "role_args": {
                                "coder": ["--custom"],
                            }
                        }
                    },
                },
            )
            with patch(_NO_USER, Path(td) / "no-user.yaml"):
                loaded = load_layered_config(project_dir)
        assert loaded.agents["coder"].args == ["--custom"]
        assert "--permission-mode" in loaded.agents["architect"].args
