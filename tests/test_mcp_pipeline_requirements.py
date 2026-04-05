from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

import agentmux.pipeline.application as application
from agentmux.runtime.tmux_control import build_agent_command
from agentmux.sessions.state_store import create_feature_files
from agentmux.shared.models import (
    AgentConfig,
    CompletionSettings,
    GitHubConfig,
    WorkflowSettings,
)
from agentmux.workflow.interruptions import InterruptionService
from agentmux.workflow.orchestrator import PipelineOrchestrator
from agentmux.workflow.prompts import (
    build_architect_prompt,
    build_product_manager_prompt,
)
from agentmux.workflow.transitions import PipelineContext


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

    def send(
        self,
        role: str,
        prompt_file: Path,
        display_label: str | None = None,
        prefix_command: str | None = None,
    ) -> None:
        _ = (role, prompt_file, display_label, prefix_command)

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

        app = application.PipelineApplication(Path("/tmp/project"))
        with (
            patch("builtins.__import__", side_effect=fake_import),
            patch(
                "agentmux.pipeline.application.ensure_watchdog_available",
                return_value=None,
            ),
            self.assertRaises(SystemExit) as exc,
        ):
            app.ensure_dependencies()

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
            files = create_feature_files(
                project_dir, feature_dir, "mcp cleanup", "session-x"
            )
            runtime = _FakeRuntime()
            orchestrator = PipelineOrchestrator(InterruptionService())
            ctx = PipelineContext(
                files=files,
                runtime=runtime,
                agents={},
                max_review_iterations=3,
                prompts={},
                github_config=GitHubConfig(),
            )

            with (
                patch(
                    "agentmux.workflow.orchestrator.PipelineOrchestrator.build_event_bus",
                    return_value=_FakeEventBus(),
                ),
                patch("agentmux.workflow.orchestrator.cleanup_mcp") as cleanup_mock,
            ):
                # Start run in a thread and trigger exit
                import threading
                import time

                result_container = {}

                def run_orchestrator() -> None:
                    result_container["result"] = orchestrator.run(
                        ctx, keep_session=False
                    )

                thread = threading.Thread(target=run_orchestrator)
                thread.start()
                time.sleep(0.05)
                if orchestrator._exit_event is not None:
                    orchestrator._exit_code = 0
                    orchestrator._exit_event.set()
                thread.join(timeout=2.0)

            self.assertEqual(0, result_container.get("result"))
            cleanup_mock.assert_called_once_with(files.feature_dir, files.project_dir)
            self.assertEqual([False], runtime.shutdown_calls)

    def test_main_calls_setup_mcp_before_runtime_creation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            base_agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", args=[]
                ),
                "product-manager": AgentConfig(
                    role="product-manager", cli="claude", model="opus", args=[]
                ),
            }
            injected_agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="claude",
                    model="opus",
                    args=[],
                    env={"PYTHONPATH": "/tmp/p"},
                ),
                "product-manager": AgentConfig(
                    role="product-manager",
                    cli="claude",
                    model="opus",
                    args=[],
                    env={"PYTHONPATH": "/tmp/p"},
                ),
            }
            loaded = SimpleNamespace(
                session_name="session-x",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents=base_agents,
                workflow_settings=WorkflowSettings(
                    completion=CompletionSettings(skip_final_approval=True),
                ),
            )
            app = application.PipelineApplication(project_dir)

            with (
                patch.object(app, "ensure_dependencies", return_value=None),
                patch(
                    "agentmux.pipeline.application.load_layered_config",
                    return_value=loaded,
                ),
                patch(
                    "agentmux.pipeline.application.tmux_session_exists",
                    return_value=False,
                ),
                patch(
                    "agentmux.integrations.github.check_gh_available",
                    return_value=False,
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                    return_value=None,
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                    return_value=injected_agents,
                ) as setup_mock,
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ) as create_mock,
                patch(
                    "agentmux.pipeline.application.PipelineApplication._start_background_orchestrator",
                    return_value=None,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run", return_value=None
                ),
            ):
                result = app.run_prompt(
                    "ship mcp", name="demo", keep_session=False, product_manager=False
                )

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
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", args=[]
                ),
            }
            injected_agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="claude",
                    model="opus",
                    args=[],
                    env={"PYTHONPATH": "/tmp/p"},
                ),
            }
            loaded = SimpleNamespace(
                session_name="session-x",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents=base_agents,
                workflow_settings=WorkflowSettings(
                    completion=CompletionSettings(skip_final_approval=True),
                ),
            )
            app = application.PipelineApplication(project_dir)

            with (
                patch.object(app, "ensure_dependencies", return_value=None),
                patch(
                    "agentmux.pipeline.application.load_layered_config",
                    return_value=loaded,
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                    side_effect=AssertionError(
                        "ensure_mcp_config should not run in orchestrate mode"
                    ),
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                    return_value=injected_agents,
                ) as setup_mock,
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.attach",
                    return_value=object(),
                ) as attach_mock,
                patch(
                    "agentmux.pipeline.application.PipelineOrchestrator.create_context",
                    return_value=object(),
                ) as create_context_mock,
                patch(
                    "agentmux.pipeline.application.PipelineOrchestrator.run",
                    return_value=0,
                ) as orchestrate_mock,
            ):
                result = app.run_orchestrate(feature_dir, keep_session=False)

            self.assertEqual(0, result)
            setup_mock.assert_called_once()
            self.assertEqual(injected_agents, attach_mock.call_args.kwargs["agents"])
            settings = create_context_mock.call_args.kwargs["workflow_settings"]
            self.assertIsInstance(settings, WorkflowSettings)
            self.assertTrue(settings.completion.skip_final_approval)
            self.assertEqual(False, orchestrate_mock.call_args.args[1])

    def test_orchestrate_mode_uses_default_workflow_settings_when_loaded_is_invalid(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            create_feature_files(project_dir, feature_dir, "resume", "session-x")

            base_agents = {
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", args=[]
                ),
            }
            loaded = SimpleNamespace(
                session_name="session-x",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents=base_agents,
                workflow_settings=SimpleNamespace(
                    completion=CompletionSettings(skip_final_approval=True),
                ),
            )
            app = application.PipelineApplication(project_dir)

            with (
                patch.object(app, "ensure_dependencies", return_value=None),
                patch(
                    "agentmux.pipeline.application.load_layered_config",
                    return_value=loaded,
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                    return_value=base_agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.attach",
                    return_value=object(),
                ),
                patch(
                    "agentmux.pipeline.application.PipelineOrchestrator.create_context",
                    return_value=object(),
                ) as create_context_mock,
                patch(
                    "agentmux.pipeline.application.PipelineOrchestrator.run",
                    return_value=0,
                ),
            ):
                result = app.run_orchestrate(feature_dir, keep_session=False)

            self.assertEqual(0, result)
            settings = create_context_mock.call_args.kwargs["workflow_settings"]
            self.assertIsInstance(settings, WorkflowSettings)
            self.assertFalse(settings.completion.skip_final_approval)

    def test_defaults_allow_mcp_research_tools_for_claude_architect_and_pm(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load(
            (
                repo_root
                / "src"
                / "agentmux"
                / "configuration"
                / "defaults"
                / "config.yaml"
            ).read_text(encoding="utf-8")
        )

        role_args = config["providers"]["claude"]["role_args"]
        self.assertIn("mcp__agentmux-research__*", role_args["architect"][-1])
        self.assertIn("mcp__agentmux-research__*", role_args["product-manager"][-1])

    def test_architect_and_product_manager_prompts_reference_mcp_tools(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(
                project_dir, feature_dir, "mcp prompt", "session-x"
            )

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
                self.assertNotIn("Fallback", prompt)


if __name__ == "__main__":
    unittest.main()
