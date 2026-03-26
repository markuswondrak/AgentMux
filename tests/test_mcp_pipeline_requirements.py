from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import agentmux.pipeline as pipeline
from agentmux.models import AgentConfig, GitHubConfig
from agentmux.prompts import build_architect_prompt, build_product_manager_prompt
from agentmux.state import create_feature_files
from agentmux.tmux import build_agent_command
from agentmux.transitions import EXIT_SUCCESS


class _FakeEventBus:
    def register(self, listener) -> None:
        _ = listener

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _FakeRuntime:
    def __init__(self) -> None:
        self.shutdown_calls: list[bool] = []

    def shutdown(self, keep_session: bool) -> None:
        self.shutdown_calls.append(keep_session)


class McpPipelineRequirementsTests(unittest.TestCase):
    def test_ensure_dependencies_requires_mcp_sdk(self) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "mcp.server.fastmcp":
                raise ImportError("missing mcp")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import), patch(
            "agentmux.pipeline.ensure_watchdog_available",
            return_value=None,
        ):
            with self.assertRaises(SystemExit) as exc:
                pipeline.ensure_dependencies()

        self.assertIn("Missing dependency: mcp.", str(exc.exception))

    def test_build_agent_command_prepends_env_prefix_when_present(self) -> None:
        command = build_agent_command(
            AgentConfig(
                role="architect",
                cli="codex",
                model="gpt-5.3-codex",
                args=["-a", "never"],
                env={"PYTHONPATH": "/tmp/project"},
            )
        )

        self.assertIn("env ", command)
        self.assertIn("PYTHONPATH=/tmp/project", command)
        self.assertIn("codex --model gpt-5.3-codex -a never", command)

    def test_orchestrate_cleans_up_mcp_artifacts_on_exit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "mcp cleanup", "session-x")
            runtime = _FakeRuntime()

            with patch(
                "agentmux.pipeline.build_orchestrator_event_bus",
                return_value=_FakeEventBus(),
            ), patch(
                "agentmux.pipeline.build_initial_prompts",
                return_value={},
            ), patch(
                "agentmux.pipeline.run_phase_cycle",
                return_value=EXIT_SUCCESS,
            ), patch("agentmux.pipeline.cleanup_mcp") as cleanup_mock:
                result = pipeline.orchestrate(
                    files=files,
                    runtime=runtime,
                    agents={},
                    max_review_iterations=3,
                    keep_session=False,
                )

            self.assertEqual(0, result)
            cleanup_mock.assert_called_once_with(files.feature_dir, files.project_dir)
            self.assertEqual([False], runtime.shutdown_calls)

    def test_main_calls_setup_mcp_before_runtime_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            base_agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
                "product-manager": AgentConfig(role="product-manager", cli="claude", model="opus", args=[]),
            }
            injected_agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[], env={"PYTHONPATH": "/tmp/p"}),
                "product-manager": AgentConfig(role="product-manager", cli="claude", model="opus", args=[], env={"PYTHONPATH": "/tmp/p"}),
            }
            loaded = SimpleNamespace(
                session_name="session-x",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents=base_agents,
            )
            args = argparse.Namespace(
                prompt="ship mcp",
                name="demo",
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=None,
                resume=None,
                issue=None,
            )

            with patch("agentmux.pipeline.parse_args", return_value=args), patch(
                "agentmux.pipeline.ensure_dependencies",
                return_value=None,
            ), patch(
                "agentmux.pipeline.Path.cwd",
                return_value=project_dir,
            ), patch(
                "agentmux.pipeline.load_runtime_config",
                return_value=loaded,
            ), patch(
                "agentmux.pipeline.tmux_session_exists",
                return_value=False,
            ), patch(
                "agentmux.pipeline.check_gh_available",
                return_value=False,
            ), patch(
                "agentmux.pipeline.ensure_mcp_config",
                return_value=None,
            ), patch(
                "agentmux.pipeline.setup_mcp",
                return_value=injected_agents,
            ) as setup_mock, patch(
                "agentmux.pipeline.TmuxAgentRuntime.create",
                return_value=object(),
            ) as create_mock, patch(
                "agentmux.pipeline.start_background_orchestrator",
                return_value=None,
            ), patch("agentmux.pipeline.subprocess.run", return_value=None):
                result = pipeline.main()

            self.assertEqual(0, result)
            setup_mock.assert_called_once()
            self.assertEqual(injected_agents, create_mock.call_args.kwargs["agents"])

    def test_main_orchestrate_mode_calls_setup_mcp_before_attach(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            create_feature_files(project_dir, feature_dir, "resume", "session-x")

            base_agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            }
            injected_agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[], env={"PYTHONPATH": "/tmp/p"}),
            }
            loaded = SimpleNamespace(
                session_name="session-x",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents=base_agents,
            )
            args = argparse.Namespace(
                prompt=None,
                name=None,
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=str(feature_dir),
                resume=None,
                issue=None,
            )

            with patch("agentmux.pipeline.parse_args", return_value=args), patch(
                "agentmux.pipeline.ensure_dependencies",
                return_value=None,
            ), patch(
                "agentmux.pipeline.Path.cwd",
                return_value=project_dir,
            ), patch(
                "agentmux.pipeline.load_runtime_config",
                return_value=loaded,
            ), patch(
                "agentmux.pipeline.ensure_mcp_config",
                side_effect=AssertionError("ensure_mcp_config should not run in orchestrate mode"),
            ), patch(
                "agentmux.pipeline.setup_mcp",
                return_value=injected_agents,
            ) as setup_mock, patch(
                "agentmux.pipeline.TmuxAgentRuntime.attach",
                return_value=object(),
            ) as attach_mock, patch(
                "agentmux.pipeline.orchestrate",
                return_value=0,
            ) as orchestrate_mock:
                result = pipeline.main()

            self.assertEqual(0, result)
            setup_mock.assert_called_once()
            self.assertEqual(injected_agents, attach_mock.call_args.kwargs["agents"])
            self.assertEqual(injected_agents, orchestrate_mock.call_args.args[2])

    def test_defaults_allow_mcp_research_tools_for_claude_architect_and_pm(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((repo_root / "agentmux" / "defaults" / "config.yaml").read_text(encoding="utf-8"))

        role_args = config["launchers"]["claude"]["role_args"]
        self.assertIn("mcp__agentmux-research__*", role_args["architect"][-1])
        self.assertIn("mcp__agentmux-research__*", role_args["product-manager"][-1])

    def test_architect_and_product_manager_prompts_reference_mcp_tools_with_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "mcp prompt", "session-x")

            architect_prompt = build_architect_prompt(files)
            product_prompt = build_product_manager_prompt(files)

            for prompt in (architect_prompt, product_prompt):
                self.assertIn("agentmux_research_dispatch_code", prompt)
                self.assertIn("agentmux_research_dispatch_web", prompt)
                self.assertNotIn("agentmux_research_await", prompt)
                self.assertIn(f'feature_dir="{feature_dir}"', prompt)
                self.assertIn("scope_hints=[", prompt)
                self.assertIn("stop and wait idle", prompt)
                self.assertIn("summary.md", prompt)
                self.assertIn("Fallback", prompt)
                self.assertIn("03_research/code-<topic>/request.md", prompt)
                self.assertIn("03_research/web-<topic>/request.md", prompt)


if __name__ == "__main__":
    unittest.main()
