from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agentmux.pipeline.application as application
import agentmux.pipeline as pipeline
from agentmux.configuration import infer_project_dir
from agentmux.terminal_ui.console import ConsoleUI
from agentmux.workflow.interruptions import InterruptionService
from agentmux.shared.models import AgentConfig, GitHubConfig, SESSION_DIR_NAMES
from agentmux.sessions import SessionRecord, SessionService
from agentmux.sessions.state_store import infer_resume_phase, write_state

PLANNING_DIR = SESSION_DIR_NAMES["planning"]
IMPLEMENTATION_DIR = SESSION_DIR_NAMES["implementation"]
REVIEW_DIR = SESSION_DIR_NAMES["review"]


class ResumeCliAndSessionTests(unittest.TestCase):
    def test_parse_args_allows_resume_without_prompt(self) -> None:
        with patch("sys.argv", ["pipeline.py", "--resume"]):
            args = pipeline.parse_args()
        self.assertTrue(args.resume)
        self.assertIsNone(args.prompt)

    def test_parse_args_accepts_resume_with_value(self) -> None:
        with patch("sys.argv", ["pipeline.py", "--resume", "20260101-120000-demo"]):
            args = pipeline.parse_args()
        self.assertEqual("20260101-120000-demo", args.resume)
        self.assertIsNone(args.prompt)

    def test_list_resumable_sessions_sorts_by_updated_at_desc(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            service = SessionService(project_dir)
            root = service.root_dir()
            older = root / "20260101-100000-older"
            newer = root / "20260101-200000-newer"
            no_state = root / "ignore-me"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            no_state.mkdir(parents=True)
            write_state(
                older / "state.json",
                {
                    "phase": "implementing",
                    "updated_at": "2026-01-01T10:00:00+01:00",
                    "last_event": "plan_written",
                },
            )
            write_state(
                newer / "state.json",
                {
                    "phase": "failed",
                    "updated_at": "2026-01-01T20:00:00+01:00",
                    "last_event": "pipeline_exception",
                },
            )

            sessions = service.list_resumable_sessions()

            self.assertEqual([newer, older], [session.feature_dir for session in sessions])

    def test_session_service_root_uses_agentmux_sessions_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            self.assertEqual(
                project_dir / ".agentmux" / ".sessions",
                SessionService(project_dir).root_dir(),
            )

    def test_console_ui_select_session_errors_when_none(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            ConsoleUI().select_session([])
        self.assertIn("No resumable sessions found", str(ctx.exception))

    def test_console_ui_auto_selects_single(self) -> None:
        session = SessionRecord(Path("/tmp/s1"), {"phase": "planning", "updated_at": "2026-01-01T10:00:00+01:00"})
        selected = ConsoleUI(output_fn=lambda _message: None).select_session([session])
        self.assertEqual(session.feature_dir, selected)

    def test_console_ui_prompts_until_valid_choice(self) -> None:
        sessions = [
            SessionRecord(
                Path("/tmp/s1"),
                {"phase": "planning", "last_event": "x", "updated_at": "2026-01-01T10:00:00+01:00"},
            ),
            SessionRecord(
                Path("/tmp/s2"),
                {"phase": "failed", "last_event": "y", "updated_at": "2026-01-01T11:00:00+01:00"},
            ),
        ]
        input_mock = Mock(side_effect=["bad", "3", "2"])
        selected = ConsoleUI(input_fn=input_mock, output_fn=lambda _message: None).select_session(sessions)
        self.assertEqual(Path("/tmp/s2"), selected)


class InferResumePhaseTests(unittest.TestCase):
    def _write_json(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def test_non_failed_phase_returns_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state = {"phase": "implementing"}
            self.assertEqual("implementing", infer_resume_phase(feature_dir, state))

    def test_failed_without_plan_resumes_planning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state = {"phase": "failed"}
            self.assertEqual("planning", infer_resume_phase(feature_dir, state))

    def test_failed_plan_with_design_required_resumes_designing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            self._write_json(feature_dir / PLANNING_DIR / "plan_meta.json", '{"needs_design": true}')
            state = {"phase": "failed"}
            self.assertEqual("designing", infer_resume_phase(feature_dir, state))

    def test_failed_fix_iteration_with_incomplete_done_markers_resumes_fixing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            (feature_dir / REVIEW_DIR / "fix_request.md").write_text("fix this", encoding="utf-8")
            state = {"phase": "failed", "review_iteration": 1, "subplan_count": 2}
            self.assertEqual("fixing", infer_resume_phase(feature_dir, state))

    def test_failed_fix_iteration_with_done_1_resumes_reviewing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            (feature_dir / REVIEW_DIR / "fix_request.md").write_text("fix this", encoding="utf-8")
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text("", encoding="utf-8")
            state = {"phase": "failed", "review_iteration": 1, "subplan_count": 2}
            self.assertEqual("reviewing", infer_resume_phase(feature_dir, state))

    def test_failed_with_incomplete_done_markers_resumes_implementing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text("", encoding="utf-8")
            state = {"phase": "failed", "subplan_count": 2}
            self.assertEqual("implementing", infer_resume_phase(feature_dir, state))

    def test_failed_with_done_markers_and_no_review_resumes_reviewing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text("", encoding="utf-8")
            state = {"phase": "failed", "subplan_count": 1}
            self.assertEqual("reviewing", infer_resume_phase(feature_dir, state))

    def test_failed_review_pass_resumes_completing_even_when_docs_metadata_is_true(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            self._write_json(
                feature_dir / PLANNING_DIR / "plan_meta.json",
                '{"needs_design": false, "needs_docs": true, "doc_files": ["docs/file-protocol.md"]}',
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text("", encoding="utf-8")
            (feature_dir / REVIEW_DIR / "review.md").write_text("Verdict: pass\n", encoding="utf-8")
            state = {"phase": "failed", "subplan_count": 1}
            self.assertEqual("completing", infer_resume_phase(feature_dir, state))

    def test_failed_review_pass_without_docs_requirement_resumes_completing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "plan.md").write_text("# Plan", encoding="utf-8")
            self._write_json(
                feature_dir / PLANNING_DIR / "plan_meta.json",
                '{"needs_design": false, "needs_docs": false, "doc_files": []}',
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text("", encoding="utf-8")
            (feature_dir / REVIEW_DIR / "review.md").write_text("Verdict: pass\n", encoding="utf-8")
            state = {"phase": "failed", "subplan_count": 1}
            self.assertEqual("completing", infer_resume_phase(feature_dir, state))

    def test_removes_dispatched_research_tasks_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state = {
                "phase": "failed",
                "research_tasks": {"a": "dispatched", "b": "done"},
                "web_research_tasks": {"x": "dispatched", "y": "done"},
            }
            infer_resume_phase(feature_dir, state)
            self.assertEqual({"b": "done"}, state["research_tasks"])
            self.assertEqual({"y": "done"}, state["web_research_tasks"])


class ResumeApplicationFlowTests(unittest.TestCase):
    def test_run_resume_with_no_sessions_exits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            args = argparse.Namespace(
                prompt=None,
                name=None,
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=None,
                resume=True,
                issue=None,
            )
            loaded = SimpleNamespace(
                session_name="multi-agent-mvp",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents={},
            )

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config",
                return_value=loaded,
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists",
                return_value=False,
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                return_value=None,
            ), patch.object(
                app.sessions,
                "list_resumable_sessions",
                return_value=[],
            ), self.assertRaises(SystemExit) as ctx:
                app.run(args)

            self.assertIn("No resumable sessions found", str(ctx.exception))

    def test_run_resume_by_name_updates_state_and_starts_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "20260101-120000-demo"
            feature_dir.mkdir(parents=True)
            initial_state = {
                "feature_dir": str(feature_dir),
                "phase": "failed",
                "last_event": "pipeline_exception",
                "subplan_count": 0,
                "review_iteration": 0,
                "research_tasks": {"a": "dispatched", "b": "done"},
                "web_research_tasks": {"x": "dispatched", "y": "done"},
                "updated_at": "2026-01-01T12:00:00+01:00",
                "updated_by": "pipeline",
            }
            write_state(feature_dir / "state.json", initial_state)

            args = argparse.Namespace(
                prompt=None,
                name=None,
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=None,
                resume="20260101-120000-demo",
                issue=None,
            )
            loaded = SimpleNamespace(
                session_name="multi-agent-mvp",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents={},
            )

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config",
                return_value=loaded,
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists",
                return_value=False,
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                return_value=None,
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                return_value={},
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                return_value=object(),
            ) as create_mock, patch.object(
                app,
                "_start_background_orchestrator",
                return_value=None,
            ) as start_mock, patch(
                "agentmux.pipeline.application.subprocess.run",
                return_value=None,
            ) as attach_mock:
                result = app.run(args)

            self.assertEqual(0, result)
            create_mock.assert_called_once()
            start_mock.assert_called_once()
            attach_mock.assert_called_once_with(
                ["tmux", "attach-session", "-t", "multi-agent-mvp"], check=True
            )
            updated_state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("planning", updated_state["phase"])
            self.assertEqual("resumed", updated_state["last_event"])
            self.assertEqual({"b": "done"}, updated_state["research_tasks"])
            self.assertEqual({"y": "done"}, updated_state["web_research_tasks"])


class InterruptionReportStateTests(unittest.TestCase):
    def test_report_from_state_canonicalizes_legacy_failed_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            service = InterruptionService()
            state = {
                "phase": "failed",
                "last_event": "pipeline_exception",
            }

            report = service.report_from_state(state, feature_dir)

            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual("failed", report.category)
            self.assertEqual("run_failed", report.last_event)
            self.assertEqual(
                "The pipeline hit an unexpected internal exception.",
                report.cause,
            )

    def test_report_from_state_ignores_none_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            service = InterruptionService()
            state = {
                "phase": "failed",
                "last_event": "run_failed",
                "interruption_category": "failed",
                "interruption_cause": "Failure summary",
                "interruption_resume_command": f"agentmux --resume {feature_dir}",
                "interruption_log_path": None,
            }

            report = service.report_from_state(state, feature_dir)

            self.assertIsNotNone(report)
            assert report is not None
            self.assertIsNone(report.log_path)
            self.assertNotIn("Diagnostics log:", service.render(report))

    def test_report_from_state_ignores_missing_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            service = InterruptionService()
            state = {
                "phase": "failed",
                "last_event": "run_failed",
                "interruption_category": "failed",
                "interruption_cause": "Failure summary",
                "interruption_resume_command": f"agentmux --resume {feature_dir}",
            }

            report = service.report_from_state(state, feature_dir)

            self.assertIsNotNone(report)
            assert report is not None
            self.assertIsNone(report.log_path)
            self.assertNotIn("Diagnostics log:", service.render(report))


class ExitMessagingTests(unittest.TestCase):
    def _loaded_config(self) -> SimpleNamespace:
        return SimpleNamespace(
            session_name="session-x",
            max_review_iterations=3,
            github=GitHubConfig(),
            agents={
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            },
        )

    def _main_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            prompt="ship feature",
            name="demo",
            config=None,
            keep_session=False,
            product_manager=False,
            orchestrate=None,
            resume=None,
            issue=None,
        )

    def test_run_ctrl_c_persists_canceled_state_and_prints_resume_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=messages.append))
            args = self._main_args()
            loaded = self._loaded_config()

            def write_log(feature_dir: Path, _keep_session: bool, product_manager: bool) -> None:
                _ = product_manager
                (feature_dir / "orchestrator.log").write_text("background log\n", encoding="utf-8")

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=loaded
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents", return_value=loaded.agents
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch.object(
                app,
                "_start_background_orchestrator",
                side_effect=write_log,
            ), patch(
                "agentmux.pipeline.application.subprocess.run", side_effect=KeyboardInterrupt
            ):
                result = app.run(args)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))

            self.assertEqual(130, result)
            self.assertEqual("failed", state["phase"])
            self.assertEqual("run_canceled", state["last_event"])
            self.assertEqual("canceled", state["interruption_category"])
            self.assertEqual(
                f"agentmux --resume {feature_dir}",
                state["interruption_resume_command"],
            )
            self.assertEqual(str(feature_dir / "orchestrator.log"), state["interruption_log_path"])
            self.assertIn("Ctrl-C", state["interruption_cause"])

            printed = "\n".join(messages)
            self.assertIn("Run canceled by user", printed)
            self.assertIn(state["interruption_resume_command"], printed)
            self.assertIn(state["interruption_log_path"], printed)

    def test_run_called_process_error_persists_failed_state_and_prints_recovery_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=messages.append))
            args = self._main_args()
            loaded = self._loaded_config()

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=loaded
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents", return_value=loaded.agents
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch.object(
                app,
                "_start_background_orchestrator",
                return_value=None,
            ), patch(
                "agentmux.pipeline.application.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    returncode=1,
                    cmd=["tmux", "attach-session", "-t", "session-x"],
                    stderr="failed to connect",
                ),
            ):
                result = app.run(args)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))

            self.assertEqual(1, result)
            self.assertEqual("failed", state["phase"])
            self.assertEqual("run_failed", state["last_event"])
            self.assertEqual("failed", state["interruption_category"])
            self.assertEqual(
                f"agentmux --resume {feature_dir}",
                state["interruption_resume_command"],
            )
            self.assertIn("exit code 1", state["interruption_cause"])

            printed = "\n".join(messages)
            self.assertIn("Run failed unexpectedly", printed)
            self.assertIn(state["interruption_resume_command"], printed)

    def test_run_reports_background_orchestrator_failure_from_persisted_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=messages.append))
            args = self._main_args()
            loaded = self._loaded_config()

            def set_failed_state(feature_dir: Path, _keep_session: bool, product_manager: bool) -> None:
                _ = product_manager
                log_path = feature_dir / "orchestrator.log"
                log_path.write_text("crash details\n", encoding="utf-8")
                state_path = feature_dir / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state.update(
                    {
                        "phase": "failed",
                        "last_event": "run_failed",
                        "interruption_category": "failed",
                        "interruption_cause": "Background orchestrator exited unexpectedly.",
                        "interruption_resume_command": f"agentmux --resume {feature_dir}",
                        "interruption_log_path": str(log_path),
                    }
                )
                write_state(state_path, state)

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=loaded
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents", return_value=loaded.agents
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch.object(
                app,
                "_start_background_orchestrator",
                side_effect=set_failed_state,
            ), patch(
                "agentmux.pipeline.application.subprocess.run", return_value=None
            ):
                result = app.run(args)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))
            printed = "\n".join(messages)

            self.assertEqual(1, result)
            self.assertEqual("run_failed", state["last_event"])
            self.assertIn(state["interruption_cause"], printed)
            self.assertIn(state["interruption_resume_command"], printed)
            self.assertIn(state["interruption_log_path"], printed)

    def test_run_treats_removed_feature_directory_as_success_after_attach_returns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=messages.append))
            args = self._main_args()
            loaded = self._loaded_config()

            def cleanup_feature_dir(feature_dir: Path, _keep_session: bool, product_manager: bool) -> None:
                _ = product_manager
                shutil.rmtree(feature_dir)

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=loaded
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents", return_value=loaded.agents
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch.object(
                app,
                "_start_background_orchestrator",
                side_effect=cleanup_feature_dir,
            ), patch(
                "agentmux.pipeline.application.subprocess.run", return_value=None
            ):
                result = app.run(args)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            self.assertEqual(0, result)
            self.assertFalse(feature_dir.exists())

    def test_run_fails_cleanly_when_state_is_missing_but_feature_directory_remains(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=lambda _message: None))
            args = self._main_args()
            loaded = self._loaded_config()

            def remove_state_only(feature_dir: Path, _keep_session: bool, product_manager: bool) -> None:
                _ = product_manager
                (feature_dir / "state.json").unlink()

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=loaded
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents", return_value=loaded.agents
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch.object(
                app,
                "_start_background_orchestrator",
                side_effect=remove_state_only,
            ), patch(
                "agentmux.pipeline.application.subprocess.run", return_value=None
            ), self.assertRaises(SystemExit) as ctx:
                app.run(args)

            self.assertIn("Session state missing after tmux exited", str(ctx.exception))
            self.assertIn("state.json", str(ctx.exception))


class ProjectDirInferenceTests(unittest.TestCase):
    def test_infer_project_dir_from_agentmux_sessions_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "20260101-120000-demo"
            self.assertEqual(project_dir, infer_project_dir(feature_dir))


if __name__ == "__main__":
    unittest.main()
