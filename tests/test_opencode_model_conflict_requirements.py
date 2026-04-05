"""Tests for opencode model conflict detection (sub-plan 4)."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agentmux.configuration import LoadedConfig
from agentmux.pipeline.application import (
    PipelineApplication,
    _extract_opencode_agent_name,
    _read_opencode_actual_model,
    _update_opencode_json,
)
from agentmux.shared.models import AgentConfig, GitHubConfig, WorkflowSettings


def _make_agent_config(
    *,
    provider: str = "opencode",
    args: list[str] | None = None,
    model: str = "sonnet",
    model_flag: str | None = "--model",
    role: str = "coder",
) -> AgentConfig:
    return AgentConfig(
        role=role,
        cli="opencode",
        model=model,
        model_flag=model_flag,
        args=args,
        provider=provider,
    )


def _make_loaded_config(
    *,
    agents: dict[str, AgentConfig],
    raw_roles: dict | None = None,
) -> LoadedConfig:
    raw: dict = {"roles": raw_roles or {}}
    return LoadedConfig(
        session_name="test-session",
        max_review_iterations=3,
        agents=agents,
        github=GitHubConfig(),
        raw=raw,
        sources=(),
        workflow_settings=WorkflowSettings(),
    )


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


class TestExtractOpencodeAgentName(unittest.TestCase):
    def test_extract_opencode_agent_name_found(self):
        agent = _make_agent_config(args=["--agent", "agentmux-coder"])
        result = _extract_opencode_agent_name(agent)
        self.assertEqual(result, "agentmux-coder")

    def test_extract_opencode_agent_name_not_found(self):
        agent = _make_agent_config(args=["--some-other-flag", "value"])
        result = _extract_opencode_agent_name(agent)
        self.assertIsNone(result)

    def test_extract_opencode_agent_name_trailing_flag(self):
        agent = _make_agent_config(args=["--agent"])
        result = _extract_opencode_agent_name(agent)
        self.assertIsNone(result)

    def test_extract_opencode_agent_name_none_args(self):
        agent = _make_agent_config(args=None)
        result = _extract_opencode_agent_name(agent)
        self.assertIsNone(result)


class TestReadOpencodeActualModel(unittest.TestCase):
    def test_read_actual_model_found(self, tmp_path=None):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"agent": {"agentmux-coder": {"model": "qwen3"}}}, f)
            path = Path(f.name)
        try:
            result = _read_opencode_actual_model(path, "agentmux-coder")
            self.assertEqual(result, "qwen3")
        finally:
            path.unlink()

    def test_read_actual_model_file_not_found(self):
        result = _read_opencode_actual_model(Path("/nonexistent/path.json"), "agent")
        self.assertIsNone(result)

    def test_read_actual_model_malformed_json(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            path = Path(f.name)
        try:
            result = _read_opencode_actual_model(path, "agent")
            self.assertIsNone(result)
        finally:
            path.unlink()

    def test_read_actual_model_missing_key(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"agent": {"other-agent": {"model": "x"}}}, f)
            path = Path(f.name)
        try:
            result = _read_opencode_actual_model(path, "agentmux-coder")
            self.assertIsNone(result)
        finally:
            path.unlink()

    def test_read_actual_model_non_string_value(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"agent": {"agentmux-coder": {"model": 42}}}, f)
            path = Path(f.name)
        try:
            result = _read_opencode_actual_model(path, "agentmux-coder")
            self.assertIsNone(result)
        finally:
            path.unlink()


class TestUpdateOpencodeJson(unittest.TestCase):
    def test_update_opencode_json_creates_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "opencode.json"
            _update_opencode_json(path, "agentmux-coder", "qwen3")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["agent"]["agentmux-coder"]["model"], "qwen3")

    def test_update_opencode_json_merges_existing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "opencode.json"
            path.write_text(
                json.dumps(
                    {"other_key": "value", "agent": {"other-agent": {"model": "x"}}}
                ),
                encoding="utf-8",
            )
            _update_opencode_json(path, "agentmux-coder", "qwen3")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["other_key"], "value")
            self.assertEqual(data["agent"]["other-agent"]["model"], "x")
            self.assertEqual(data["agent"]["agentmux-coder"]["model"], "qwen3")

    def test_update_opencode_json_overwrites_model(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "opencode.json"
            path.write_text(
                json.dumps({"agent": {"agentmux-coder": {"model": "old-model"}}}),
                encoding="utf-8",
            )
            _update_opencode_json(path, "agentmux-coder", "new-model")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["agent"]["agentmux-coder"]["model"], "new-model")


# ---------------------------------------------------------------------------
# Conflict checker integration tests
# ---------------------------------------------------------------------------


class TestConflictChecker(unittest.TestCase):
    def _make_app(self, tmp_path: Path) -> PipelineApplication:
        return PipelineApplication(project_dir=tmp_path)

    def test_conflict_y_continues(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {"coder": _make_agent_config(args=["--agent", "agentmux-coder"])}
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"model": "qwen3", "provider": "opencode"}},
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = "y"

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertTrue(result)

    def test_conflict_n_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {"coder": _make_agent_config(args=["--agent", "agentmux-coder"])}
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"model": "qwen3", "provider": "opencode"}},
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = "n"

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertFalse(result)

    def test_conflict_empty_input_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {"coder": _make_agent_config(args=["--agent", "agentmux-coder"])}
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"model": "qwen3", "provider": "opencode"}},
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = ""

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertFalse(result)

    def test_conflict_a_updates_json_and_continues(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {"coder": _make_agent_config(args=["--agent", "agentmux-coder"])}
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"model": "qwen3", "provider": "opencode"}},
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = "a"

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertTrue(result)

            opencode_path = tmp_path / "opencode.json"
            self.assertTrue(opencode_path.exists())
            data = json.loads(opencode_path.read_text(encoding="utf-8"))
            self.assertEqual(data["agent"]["agentmux-coder"]["model"], "qwen3")

    def test_conflict_a_ioerror_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {"coder": _make_agent_config(args=["--agent", "agentmux-coder"])}
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"model": "qwen3", "provider": "opencode"}},
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = "a"

            # Make opencode.json a directory so writing fails
            opencode_path = tmp_path / "opencode.json"
            opencode_path.mkdir()

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertFalse(result)

    def test_conflict_multiple_roles_first_n_aborts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {
                "coder": _make_agent_config(args=["--agent", "agentmux-coder"]),
                "architect": _make_agent_config(
                    args=["--agent", "agentmux-architect"], role="architect"
                ),
            }
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={
                    "coder": {"model": "qwen3", "provider": "opencode"},
                    "architect": {"model": "opus", "provider": "opencode"},
                },
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = "n"

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertFalse(result)
            # Should only be called once (first role aborts immediately)
            self.assertEqual(app.ui.input_fn.call_count, 1)

    def test_conflict_multiple_roles_all_y(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {
                "coder": _make_agent_config(args=["--agent", "agentmux-coder"]),
                "architect": _make_agent_config(
                    args=["--agent", "agentmux-architect"], role="architect"
                ),
            }
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={
                    "coder": {"model": "qwen3", "provider": "opencode"},
                    "architect": {"model": "opus", "provider": "opencode"},
                },
            )
            app.ui = MagicMock()
            app.ui.input_fn.return_value = "y"

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertTrue(result)
            # Should be called twice (once per role)
            self.assertEqual(app.ui.input_fn.call_count, 2)

    def test_no_conflict_non_opencode_provider(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {
                "coder": _make_agent_config(
                    provider="claude", args=["--agent", "agentmux-coder"]
                )
            }
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"model": "qwen3", "provider": "claude"}},
            )
            app.ui = MagicMock()

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertTrue(result)
            app.ui.input_fn.assert_not_called()

    def test_no_conflict_opencode_no_model_in_raw(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            app = self._make_app(tmp_path)
            agents = {"coder": _make_agent_config(args=["--agent", "agentmux-coder"])}
            loaded = _make_loaded_config(
                agents=agents,
                raw_roles={"coder": {"provider": "opencode"}},  # no model key
            )
            app.ui = MagicMock()

            result = app._check_opencode_model_conflicts(loaded, tmp_path)
            self.assertTrue(result)
            app.ui.input_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
