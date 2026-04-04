from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agentmux.pipeline.application as application
from agentmux.configuration import infer_project_dir
from agentmux.sessions import SessionRecord, SessionService
from agentmux.sessions.state_store import infer_resume_phase, write_state
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig, GitHubConfig
from agentmux.terminal_ui.console import ConsoleUI
from agentmux.workflow.interruptions import InterruptionService
from agentmux.workflow.phase_registry import resolve_phase_startup_role

PLANNING_DIR = SESSION_DIR_NAMES["planning"]
IMPLEMENTATION_DIR = SESSION_DIR_NAMES["implementation"]
REVIEW_DIR = SESSION_DIR_NAMES["review"]


def _agent(role: str) -> AgentConfig:
    return AgentConfig(role=role, cli="copilot", model="test-model")


class ResumeCliAndSessionTests(unittest.TestCase):
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
                    "last_event": "run_failed",
                },
            )

            sessions = service.list_resumable_sessions()

            self.assertEqual(
                [newer, older], [session.feature_dir for session in sessions]
            )

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
        session = SessionRecord(
            Path("/tmp/s1"),
            {"phase": "planning", "updated_at": "2026-01-01T10:00:00+01:00"},
        )
        selected = ConsoleUI(output_fn=lambda _message: None).select_session([session])
        self.assertEqual(session.feature_dir, selected)

    def test_console_ui_prompts_until_valid_choice(self) -> None:
        sessions = [
            SessionRecord(
                Path("/tmp/s1"),
                {
                    "phase": "planning",
                    "last_event": "x",
                    "updated_at": "2026-01-01T10:00:00+01:00",
                },
            ),
            SessionRecord(
                Path("/tmp/s2"),
                {
                    "phase": "failed",
                    "last_event": "y",
                    "updated_at": "2026-01-01T11:00:00+01:00",
                },
            ),
        ]
        input_mock = Mock(side_effect=["bad", "3", "2"])
        selected = ConsoleUI(
            input_fn=input_mock, output_fn=lambda _message: None
        ).select_session(sessions)
        self.assertEqual(Path("/tmp/s2"), selected)


class InferResumePhaseTests(unittest.TestCase):
    def _write_json(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")

    def test_non_failed_phase_returns_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state = {"phase": "implementing"}
            self.assertEqual("implementing", infer_resume_phase(feature_dir, state))

    def test_failed_without_architecture_resumes_architecting(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state = {"phase": "failed"}
            self.assertEqual("architecting", infer_resume_phase(feature_dir, state))

    def test_failed_with_architecture_but_no_plan_resumes_planning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            state = {"phase": "failed"}
            self.assertEqual("planning", infer_resume_phase(feature_dir, state))

    def test_failed_plan_with_design_required_resumes_designing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            self._write_json(
                feature_dir / PLANNING_DIR / "plan_meta.json", '{"needs_design": true}'
            )
            state = {"phase": "failed"}
            self.assertEqual("designing", infer_resume_phase(feature_dir, state))

    def test_failed_fix_iteration_with_incomplete_done_markers_resumes_fixing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            (feature_dir / REVIEW_DIR / "fix_request.md").write_text(
                "fix this", encoding="utf-8"
            )
            state = {"phase": "failed", "review_iteration": 1, "subplan_count": 2}
            self.assertEqual("fixing", infer_resume_phase(feature_dir, state))

    def test_failed_fix_iteration_with_done_1_resumes_reviewing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            (feature_dir / REVIEW_DIR / "fix_request.md").write_text(
                "fix this", encoding="utf-8"
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text(
                "", encoding="utf-8"
            )
            state = {"phase": "failed", "review_iteration": 1, "subplan_count": 2}
            self.assertEqual("reviewing", infer_resume_phase(feature_dir, state))

    def test_failed_with_incomplete_done_markers_resumes_implementing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text(
                "", encoding="utf-8"
            )
            state = {"phase": "failed", "subplan_count": 2}
            self.assertEqual("implementing", infer_resume_phase(feature_dir, state))

    def test_failed_with_done_markers_and_no_review_resumes_reviewing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text(
                "", encoding="utf-8"
            )
            state = {"phase": "failed", "subplan_count": 1}
            self.assertEqual("reviewing", infer_resume_phase(feature_dir, state))

    def test_failed_review_pass_resumes_completing_even_when_docs_metadata_is_true(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            self._write_json(
                feature_dir / PLANNING_DIR / "plan_meta.json",
                (
                    '{"needs_design": false, "needs_docs": true, '
                    '"doc_files": ["docs/file-protocol.md"]}'
                ),
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text(
                "", encoding="utf-8"
            )
            (feature_dir / REVIEW_DIR / "review.md").write_text(
                "Verdict: pass\n", encoding="utf-8"
            )
            state = {"phase": "failed", "subplan_count": 1}
            self.assertEqual("completing", infer_resume_phase(feature_dir, state))

    def test_failed_review_pass_without_docs_requirement_resumes_completing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / IMPLEMENTATION_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / REVIEW_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PLANNING_DIR / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan", encoding="utf-8"
            )
            self._write_json(
                feature_dir / PLANNING_DIR / "plan_meta.json",
                '{"needs_design": false, "needs_docs": false, "doc_files": []}',
            )
            (feature_dir / IMPLEMENTATION_DIR / "done_1").write_text(
                "", encoding="utf-8"
            )
            (feature_dir / REVIEW_DIR / "review.md").write_text(
                "Verdict: pass\n", encoding="utf-8"
            )
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


class ResumeStartupRoleTests(unittest.TestCase):
    def test_resolve_phase_startup_role_uses_planner_for_planning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            agents = {
                "architect": _agent("architect"),
                "planner": _agent("planner"),
                "product-manager": _agent("product-manager"),
            }

            role = resolve_phase_startup_role(
                "planning",
                feature_dir,
                {"phase": "planning", "product_manager": True},
                agents,
            )

            self.assertEqual("planner", role)

    def test_resolve_phase_startup_role_uses_review_strategy_for_reviewing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            planning_dir = feature_dir / PLANNING_DIR
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "plan_meta.json").write_text(
                json.dumps(
                    {
                        "review_strategy": {
                            "severity": "high",
                            "focus": ["security"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            agents = {
                "reviewer_logic": _agent("reviewer_logic"),
                "reviewer_quality": _agent("reviewer_quality"),
                "reviewer_expert": _agent("reviewer_expert"),
            }

            role = resolve_phase_startup_role(
                "reviewing",
                feature_dir,
                {"phase": "reviewing"},
                agents,
            )

            self.assertEqual("reviewer_expert", role)


class ResumeApplicationFlowTests(unittest.TestCase):
    def test_run_resume_with_no_sessions_exits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            loaded = SimpleNamespace(
                session_name="multi-agent-mvp",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents={},
            )

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
                    "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                    return_value=None,
                ),
                patch.object(
                    app.sessions,
                    "list_resumable_sessions",
                    return_value=[],
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                app.run_resume()

            self.assertIn("No resumable sessions found", str(ctx.exception))

    def test_run_resume_by_name_updates_state_and_starts_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = (
                project_dir / ".agentmux" / ".sessions" / "20260101-120000-demo"
            )
            feature_dir.mkdir(parents=True)
            (feature_dir / "01_product_management").mkdir(parents=True, exist_ok=True)
            (feature_dir / "01_product_management" / "done").write_text(
                "", encoding="utf-8"
            )
            planning_dir = feature_dir / "02_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            initial_state = {
                "feature_dir": str(feature_dir),
                "phase": "failed",
                "last_event": "run_failed",
                "product_manager": True,
                "subplan_count": 0,
                "review_iteration": 0,
                "research_tasks": {"a": "dispatched", "b": "done"},
                "web_research_tasks": {"x": "dispatched", "y": "done"},
                "updated_at": "2026-01-01T12:00:00+01:00",
                "updated_by": "pipeline",
            }
            write_state(feature_dir / "state.json", initial_state)

            loaded = SimpleNamespace(
                session_name="multi-agent-mvp",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents={
                    "architect": _agent("architect"),
                    "planner": _agent("planner"),
                    "product-manager": _agent("product-manager"),
                },
            )

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
                    "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                    return_value=None,
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ) as create_mock,
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    return_value=None,
                ) as start_mock,
                patch(
                    "agentmux.pipeline.application.subprocess.run",
                    return_value=None,
                ) as attach_mock,
            ):
                result = app.run_resume(session="20260101-120000-demo")

            self.assertEqual(0, result)
            create_mock.assert_called_once()
            self.assertEqual("planner", create_mock.call_args.kwargs["initial_role"])
            start_mock.assert_called_once()
            attach_mock.assert_called_once_with(
                ["tmux", "attach-session", "-t", "multi-agent-mvp"], check=True
            )
            updated_state = json.loads(
                (feature_dir / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("planning", updated_state["phase"])
            self.assertEqual("resumed", updated_state["last_event"])
            self.assertEqual({"b": "done"}, updated_state["research_tasks"])
            self.assertEqual({"y": "done"}, updated_state["web_research_tasks"])

    def test_run_resume_non_failed_planning_state_uses_planner_initial_role(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            feature_dir = (
                project_dir / ".agentmux" / ".sessions" / "20260101-120000-demo"
            )
            feature_dir.mkdir(parents=True)
            (feature_dir / "01_product_management").mkdir(parents=True, exist_ok=True)
            (feature_dir / "01_product_management" / "done").write_text(
                "", encoding="utf-8"
            )
            planning_dir = feature_dir / PLANNING_DIR
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "architecture.md").write_text(
                "# Architecture", encoding="utf-8"
            )
            write_state(
                feature_dir / "state.json",
                {
                    "feature_dir": str(feature_dir),
                    "phase": "planning",
                    "last_event": "architecture_written",
                    "product_manager": True,
                    "updated_at": "2026-01-01T12:00:00+01:00",
                    "updated_by": "pipeline",
                },
            )

            loaded = SimpleNamespace(
                session_name="multi-agent-mvp",
                max_review_iterations=3,
                github=GitHubConfig(),
                agents={
                    "architect": _agent("architect"),
                    "planner": _agent("planner"),
                    "product-manager": _agent("product-manager"),
                },
            )

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
                    "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config",
                    return_value=None,
                ),
                patch(
                    "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ) as create_mock,
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    return_value=None,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run",
                    return_value=None,
                ),
            ):
                result = app.run_resume(session="20260101-120000-demo")

            self.assertEqual(0, result)
            self.assertEqual("planner", create_mock.call_args.kwargs["initial_role"])


class InterruptionReportStateTests(unittest.TestCase):
    def test_report_from_state_uses_default_cause_for_unknown_failed_event(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            service = InterruptionService()
            state = {
                "phase": "failed",
                "last_event": "run_failed",
            }

            report = service.report_from_state(state, feature_dir)

            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual("failed", report.category)
            self.assertEqual("run_failed", report.last_event)
            self.assertEqual(
                "The pipeline failed unexpectedly.",
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
                "interruption_resume_command": f"agentmux resume {feature_dir}",
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
                "interruption_resume_command": f"agentmux resume {feature_dir}",
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
                "architect": AgentConfig(
                    role="architect", cli="claude", model="opus", args=[]
                ),
            },
        )

    def _run_main(self, app: application.PipelineApplication) -> int:
        return app.run_prompt("ship feature", name="demo")

    def test_run_ctrl_c_persists_canceled_state_and_prints_resume_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(
                project_dir, ui=ConsoleUI(output_fn=messages.append)
            )

            loaded = self._loaded_config()

            def write_log(feature_dir: Path, _keep_session: bool) -> None:
                (feature_dir / "orchestrator.log").write_text(
                    "background log\n", encoding="utf-8"
                )

            def subprocess_run_side_effect(args, **kwargs):
                if args[0:2] == ["tmux", "attach-session"]:
                    raise KeyboardInterrupt
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="", stderr=""
                )

            stdout_buffer = io.StringIO()
            with (
                patch("sys.stdout", stdout_buffer),
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
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ),
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    side_effect=write_log,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run",
                    side_effect=subprocess_run_side_effect,
                ),
            ):
                result = self._run_main(app)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))

            self.assertEqual(130, result)
            self.assertEqual("failed", state["phase"])
            self.assertEqual("run_canceled", state["last_event"])
            self.assertEqual("canceled", state["interruption_category"])
            self.assertEqual(
                f"agentmux resume {feature_dir.name}",
                state["interruption_resume_command"],
            )
            self.assertEqual(
                str(feature_dir / "orchestrator.log"), state["interruption_log_path"]
            )
            self.assertIn("Ctrl-C", state["interruption_cause"])

            captured = stdout_buffer.getvalue()
            self.assertIn("Run canceled by user", captured)
            self.assertIn(state["interruption_resume_command"], captured)
            self.assertIn(state["interruption_log_path"], captured)

    def test_run_called_process_error_persists_failed_state_and_prints_recovery_message(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(
                project_dir, ui=ConsoleUI(output_fn=messages.append)
            )

            loaded = self._loaded_config()

            stdout_buffer = io.StringIO()
            with (
                patch("sys.stdout", stdout_buffer),
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
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ),
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    return_value=None,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run",
                    side_effect=subprocess.CalledProcessError(
                        returncode=1,
                        cmd=["tmux", "attach-session", "-t", "session-x"],
                        stderr="failed to connect",
                    ),
                ),
            ):
                result = self._run_main(app)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))

            self.assertEqual(1, result)
            self.assertEqual("failed", state["phase"])
            self.assertEqual("run_failed", state["last_event"])
            self.assertEqual("failed", state["interruption_category"])
            self.assertEqual(
                f"agentmux resume {feature_dir.name}",
                state["interruption_resume_command"],
            )
            self.assertIn("exit code 1", state["interruption_cause"])

            captured = stdout_buffer.getvalue()
            self.assertIn("Run failed unexpectedly", captured)
            self.assertIn(state["interruption_resume_command"], captured)

    def test_run_reports_background_orchestrator_failure_from_persisted_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(
                project_dir, ui=ConsoleUI(output_fn=messages.append)
            )

            loaded = self._loaded_config()

            def set_failed_state(feature_dir: Path, _keep_session: bool) -> None:
                log_path = feature_dir / "orchestrator.log"
                log_path.write_text("crash details\n", encoding="utf-8")
                state_path = feature_dir / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state.update(
                    {
                        "phase": "failed",
                        "last_event": "run_failed",
                        "interruption_category": "failed",
                        "interruption_cause": "Background orchestrator exited.",
                        "interruption_resume_command": f"agentmux resume {feature_dir}",
                        "interruption_log_path": str(log_path),
                    }
                )
                write_state(state_path, state)

            stdout_buffer = io.StringIO()
            with (
                patch("sys.stdout", stdout_buffer),
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
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ),
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    side_effect=set_failed_state,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run", return_value=None
                ),
            ):
                result = self._run_main(app)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))
            captured = stdout_buffer.getvalue()

            self.assertEqual(1, result)
            self.assertEqual("run_failed", state["last_event"])
            self.assertIn(state["interruption_cause"], captured)
            self.assertIn(state["interruption_resume_command"], captured)
            self.assertIn(state["interruption_log_path"], captured)

    def test_run_treats_removed_feature_directory_as_success_after_attach_returns(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(
                project_dir, ui=ConsoleUI(output_fn=messages.append)
            )

            loaded = self._loaded_config()

            def cleanup_feature_dir(feature_dir: Path, _keep_session: bool) -> None:
                shutil.rmtree(feature_dir)

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
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ),
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    side_effect=cleanup_feature_dir,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run", return_value=None
                ),
            ):
                result = self._run_main(app)

            feature_dir = project_dir / ".agentmux" / ".sessions" / "demo"
            self.assertEqual(0, result)
            self.assertFalse(feature_dir.exists())

    def test_run_fails_cleanly_when_state_is_missing_but_feature_directory_remains(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(
                project_dir, ui=ConsoleUI(output_fn=lambda _message: None)
            )

            loaded = self._loaded_config()

            def remove_state_only(feature_dir: Path, _keep_session: bool) -> None:
                (feature_dir / "state.json").unlink()

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
                    return_value=loaded.agents,
                ),
                patch(
                    "agentmux.pipeline.application.TmuxRuntimeFactory.create",
                    return_value=object(),
                ),
                patch.object(
                    app,
                    "_start_background_orchestrator",
                    side_effect=remove_state_only,
                ),
                patch(
                    "agentmux.pipeline.application.subprocess.run", return_value=None
                ),
                self.assertRaises(SystemExit) as ctx,
            ):
                self._run_main(app)

            self.assertIn("Session state missing after tmux exited", str(ctx.exception))
            self.assertIn("state.json", str(ctx.exception))


class ProjectDirInferenceTests(unittest.TestCase):
    def test_infer_project_dir_from_agentmux_sessions_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            feature_dir = (
                project_dir / ".agentmux" / ".sessions" / "20260101-120000-demo"
            )
            self.assertEqual(project_dir, infer_project_dir(feature_dir))


if __name__ == "__main__":
    unittest.main()
