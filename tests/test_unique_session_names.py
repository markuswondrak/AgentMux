from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agentmux.pipeline.application as application
from agentmux.runtime.tmux_control import list_agentmux_sessions
from agentmux.sessions import PreparedSession
from agentmux.sessions.state_store import create_feature_files
from agentmux.shared.models import GitHubConfig
from agentmux.terminal_ui.console import ConsoleUI


class UniqueSessionNamesTests(unittest.TestCase):
    def test_list_agentmux_sessions_filters_prefix(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["tmux", "list-sessions", "-F", "#{session_name}"],
            returncode=0,
            stdout="agentmux-a\nlegacy\nagentmux-b\n",
            stderr="",
        )

        with patch("agentmux.runtime.tmux_control.run_command", return_value=completed):
            sessions = list_agentmux_sessions()

        self.assertEqual(["agentmux-a", "agentmux-b"], sessions)

    def test_create_feature_files_persists_session_name_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            feature_dir = (
                project_dir / ".agentmux" / ".sessions" / "20260328-000000-demo"
            )
            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="implement unique session names",
                session_name="agentmux-20260328-000000-demo",
            )
            state = json.loads(files.state.read_text(encoding="utf-8"))
            self.assertEqual("agentmux-20260328-000000-demo", state.get("session_name"))

    def test_derive_session_name_uses_feature_directory_name(self) -> None:
        feature_dir = Path("/tmp/project/.agentmux/.sessions/20260328-000000-demo")
        self.assertEqual(
            "agentmux-20260328-000000-demo",
            application._derive_session_name(feature_dir),
        )

    def test_run_launcher_does_not_block_non_resume_when_default_session_exists(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="prompt",
                session_name="legacy-name",
            )
            prepared = PreparedSession(
                feature_dir=feature_dir, files=files, product_manager=False
            )
            args = SimpleNamespace(resume=None, issue=None)
            loaded = SimpleNamespace(agents={}, session_name="multi-agent-mvp")
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(app, "_prepare_session", return_value=prepared),
                patch.object(
                    app, "_launch_attached_session", return_value=0
                ) as launch_mock,
                patch(
                    "agentmux.pipeline.application.tmux_session_exists",
                    return_value=True,
                ),
            ):
                result = app._run_launcher(args, loaded)

            self.assertEqual(0, result)
            launch_mock.assert_called_once()

    def test_run_launcher_derives_and_persists_session_name_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(
                project_dir, ui=ConsoleUI(output_fn=messages.append)
            )
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="prompt",
                session_name="legacy-name",
            )
            prepared = PreparedSession(
                feature_dir=feature_dir, files=files, product_manager=False
            )
            args = SimpleNamespace(resume=None, issue=None)
            loaded = SimpleNamespace(agents={}, session_name="multi-agent-mvp")
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(app, "_prepare_session", return_value=prepared),
                patch.object(app, "_launch_attached_session", return_value=0),
                patch(
                    "agentmux.pipeline.application.list_agentmux_sessions",
                    return_value=["agentmux-existing"],
                ),
            ):
                result = app._run_launcher(args, loaded)

            self.assertEqual(0, result)
            state = json.loads(files.state.read_text(encoding="utf-8"))
            self.assertEqual("agentmux-demo", state.get("session_name"))
            self.assertIn(
                "Warning: Other agentmux session(s) running: agentmux-existing",
                files.orchestrator_log.read_text(encoding="utf-8"),
            )

    def test_run_launcher_passes_resolved_session_name_to_launch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="prompt",
                session_name="legacy-name",
            )
            prepared = PreparedSession(
                feature_dir=feature_dir, files=files, product_manager=False
            )
            args = SimpleNamespace(resume=None, issue=None)
            loaded = SimpleNamespace(agents={}, session_name="multi-agent-mvp")
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(app, "_prepare_session", return_value=prepared),
                patch.object(
                    app, "_launch_attached_session", return_value=0
                ) as launch_mock,
                patch(
                    "agentmux.pipeline.application.list_agentmux_sessions",
                    return_value=[],
                ),
            ):
                result = app._run_launcher(args, loaded)

            self.assertEqual(0, result)
            self.assertEqual(
                "agentmux-demo", launch_mock.call_args.kwargs.get("session_name")
            )

    def test_background_orchestrator_uses_session_name_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            feature_dir.mkdir(parents=True, exist_ok=True)
            (feature_dir / "state.json").write_text(
                json.dumps({"session_name": "agentmux-demo"}, indent=2) + "\n",
                encoding="utf-8",
            )

            app = application.PipelineApplication(project_dir)
            args = SimpleNamespace(orchestrate=str(feature_dir), keep_session=False)
            loaded = SimpleNamespace(
                agents={},
                max_review_iterations=3,
                github=GitHubConfig(),
                session_name="multi-agent-mvp",
            )
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(
                    app.runtime_factory,
                    "attach",
                    return_value=object(),
                ) as attach_mock,
                patch.object(
                    app.orchestrator,
                    "create_context",
                    return_value=object(),
                ),
                patch.object(
                    app.orchestrator,
                    "run",
                    return_value=0,
                ),
            ):
                result = app._run_background_orchestrator(args, loaded)

            self.assertEqual(0, result)
            self.assertEqual(
                "agentmux-demo", attach_mock.call_args.kwargs.get("session_name")
            )

    def test_background_orchestrator_falls_back_to_loaded_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            feature_dir.mkdir(parents=True, exist_ok=True)
            (feature_dir / "state.json").write_text(
                json.dumps({"phase": "planning"}, indent=2) + "\n",
                encoding="utf-8",
            )

            app = application.PipelineApplication(project_dir)
            args = SimpleNamespace(orchestrate=str(feature_dir), keep_session=False)
            loaded = SimpleNamespace(
                agents={},
                max_review_iterations=3,
                github=GitHubConfig(),
                session_name="multi-agent-mvp",
            )
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(
                    app.runtime_factory,
                    "attach",
                    return_value=object(),
                ) as attach_mock,
                patch.object(
                    app.orchestrator,
                    "create_context",
                    return_value=object(),
                ),
                patch.object(
                    app.orchestrator,
                    "run",
                    return_value=0,
                ),
            ):
                result = app._run_background_orchestrator(args, loaded)

            self.assertEqual(0, result)
            self.assertEqual(
                "multi-agent-mvp", attach_mock.call_args.kwargs.get("session_name")
            )

    def test_run_launcher_resume_blocks_when_recovered_session_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="prompt",
                session_name="legacy-name",
            )
            state = json.loads(files.state.read_text(encoding="utf-8"))
            state["session_name"] = "agentmux-demo"
            files.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            prepared = PreparedSession(
                feature_dir=feature_dir, files=files, product_manager=False
            )
            args = SimpleNamespace(resume="demo", issue=None)
            loaded = SimpleNamespace(agents={}, session_name="multi-agent-mvp")
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(app, "_prepare_session", return_value=prepared),
                patch.object(app, "_launch_attached_session", return_value=0),
                patch(
                    "agentmux.pipeline.application.tmux_session_exists",
                    return_value=True,
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                app._run_launcher(args, loaded)

            self.assertIn(
                "tmux session `agentmux-demo` is still active", str(ctx.exception)
            )

    def test_run_launcher_resume_uses_loaded_session_name_for_legacy_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            files = create_feature_files(
                project_dir=project_dir,
                feature_dir=feature_dir,
                prompt="prompt",
                session_name="legacy-name",
            )
            state = json.loads(files.state.read_text(encoding="utf-8"))
            state.pop("session_name", None)
            files.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            prepared = PreparedSession(
                feature_dir=feature_dir, files=files, product_manager=False
            )
            args = SimpleNamespace(resume="demo", issue=None)
            loaded = SimpleNamespace(agents={}, session_name="multi-agent-mvp")
            mcp = Mock()
            mcp.prepare_feature_agents.return_value = {}

            with (
                patch.object(app, "_mcp_preparer", return_value=mcp),
                patch.object(app, "_prepare_session", return_value=prepared),
                patch.object(app, "_launch_attached_session", return_value=0),
                patch(
                    "agentmux.pipeline.application.tmux_session_exists",
                    return_value=True,
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                app._run_launcher(args, loaded)

            self.assertIn(
                "tmux session `multi-agent-mvp` is still active", str(ctx.exception)
            )


if __name__ == "__main__":
    unittest.main()
