from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any

from ..configuration import load_layered_config
from ..integrations.git_manager import GitBranchManager
from ..integrations.github import GitHubBootstrapper
from ..integrations.mcp import McpAgentPreparer
from ..runtime import TmuxRuntimeFactory
from ..runtime.file_events import ensure_watchdog_available
from ..runtime.tmux_control import list_agentmux_sessions, tmux_session_exists
from ..sessions import (
    PreparedSession,
    PromptInput,
    SessionCreateRequest,
    SessionService,
)
from ..sessions.state_store import (
    feature_slug_from_dir,
    load_runtime_files,
    load_state,
    write_state,
)
from ..shared.models import WorkflowSettings
from ..terminal_ui.console import ConsoleUI
from ..terminal_ui.screens import goodbye_canceled, goodbye_error, goodbye_success
from ..workflow.interruptions import InterruptionService
from ..workflow.orchestrator import PipelineOrchestrator
from ..workflow.phase_registry import resolve_phase_startup_role


def _derive_session_name(feature_dir: Path) -> str:
    """Derive a unique tmux session name from the feature directory."""
    return f"agentmux-{feature_dir.name}"


def _coalesce_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _read_initial_request_line(requirements_path: Path) -> str:
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    in_initial_request = False
    for line in lines:
        stripped = line.strip()
        if not in_initial_request:
            if stripped == "## Initial Request":
                in_initial_request = True
            continue
        if stripped.startswith("## "):
            break
        if stripped:
            return stripped
    return ""


def _read_last_completion(project_dir: Path) -> dict[str, str | None]:
    from ..shared.models import ProjectPaths

    paths = ProjectPaths.from_project(project_dir)
    summary_path = paths.last_completion
    if not summary_path.exists():
        return {}
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    feature_name = _coalesce_text(payload.get("feature_name"))
    commit_hash = _coalesce_text(payload.get("commit_hash"))
    branch_name = _coalesce_text(payload.get("branch_name"))
    pr_url_raw = _coalesce_text(payload.get("pr_url"))
    return {
        "feature_name": feature_name or None,
        "commit_hash": commit_hash or None,
        "pr_url": pr_url_raw or None,
        "branch_name": branch_name or None,
    }


class PipelineApplication:
    def __init__(
        self,
        project_dir: Path,
        config_path: Path | None = None,
        ui: ConsoleUI | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.config_path = config_path
        self.ui = ui or ConsoleUI()
        self.interruptions = InterruptionService()
        self.sessions = SessionService(project_dir)
        self.runtime_factory = TmuxRuntimeFactory()
        self.orchestrator = PipelineOrchestrator(self.interruptions)

    def ensure_dependencies(self) -> None:
        ensure_watchdog_available()
        try:
            from mcp.server.fastmcp import FastMCP  # noqa: F401
        except ImportError as exc:
            raise SystemExit(
                "Missing dependency: mcp. "
                "Install it with `python3 -m pip install -r requirements.txt`."
            ) from exc

    def _run_background_orchestrator(self, args, loaded) -> int:
        feature_dir = Path(args.orchestrate).resolve()
        agents = self._mcp_preparer().prepare_feature_agents(loaded.agents, feature_dir)
        if getattr(loaded, "compression_enabled", False):
            from agentmux.integrations.compression import (
                inject_compression_env,
                read_proxy_port,
            )

            port = read_proxy_port(feature_dir)
            if port is not None:
                agents = inject_compression_env(agents, port)
        files = load_runtime_files(self.project_dir, feature_dir)
        state = load_state(feature_dir / "state.json")
        session_name = str(state.get("session_name") or loaded.session_name)
        runtime = self.runtime_factory.attach(
            feature_dir=feature_dir,
            project_dir=self.project_dir,
            session_name=session_name,
            agents=agents,
        )
        ctx = self.orchestrator.create_context(
            files,
            runtime,
            agents,
            loaded.max_review_iterations,
            loaded.github,
            workflow_settings=self._resolve_workflow_settings(loaded),
        )
        try:
            return self.orchestrator.run(ctx, args.keep_session)
        except KeyboardInterrupt:
            self._cleanup_runtime_processes(runtime)
            report = self.interruptions.build_canceled(
                feature_dir,
                "The background orchestrator received Ctrl-C.",
                files=files,
            )
            self.interruptions.persist(files, report)
            self.ui.print(self.interruptions.render(report))
            return 130
        except Exception as exc:
            self._cleanup_runtime_processes(runtime)
            report = self.interruptions.build_failed(
                feature_dir,
                self.interruptions.summarize_exception(
                    exc,
                    context="The background orchestrator crashed unexpectedly.",
                ),
                files=files,
            )
            self.interruptions.persist(files, report)
            self.ui.print(self.interruptions.render(report))
            return 1

    def _cleanup_runtime_processes(self, runtime) -> None:
        """Kill all tracked processes for a runtime instance.

        This is a best-effort cleanup that silently ignores any errors.
        Used when the runtime object is already available.
        """
        with contextlib.suppress(Exception):
            runtime.kill_tracked_processes(timeout=5.0)  # Best effort cleanup

    def _resolve_workflow_settings(self, loaded) -> WorkflowSettings:
        candidate = getattr(loaded, "workflow_settings", None)
        if isinstance(candidate, WorkflowSettings):
            return candidate
        return WorkflowSettings()

    def _run_launcher(self, args, loaded) -> int:
        if args.resume and getattr(args, "issue", None):
            raise SystemExit("--issue cannot be used with --resume.")

        mcp = self._mcp_preparer()
        mcp.ensure_project_config(loaded.agents)

        prepared = self._prepare_session(args, loaded)
        if args.resume:
            state = load_state(prepared.files.state)
            session_name = str(state.get("session_name") or loaded.session_name)
            if tmux_session_exists(session_name):
                raise SystemExit(
                    f"tmux session `{session_name}` is still active. "
                    "Detach or kill it before resuming."
                )
        else:
            session_name = _derive_session_name(prepared.feature_dir)
            state = load_state(prepared.files.state)
            state["session_name"] = session_name
            write_state(prepared.files.state, state)
            existing_sessions = [
                name for name in list_agentmux_sessions() if name != session_name
            ]
            if existing_sessions:
                with prepared.files.orchestrator_log.open("a", encoding="utf-8") as _f:
                    _f.write(
                        "Warning: Other agentmux session(s) running: "
                        f"{', '.join(existing_sessions)}\n"
                    )

        agents = mcp.prepare_feature_agents(loaded.agents, prepared.feature_dir)
        if getattr(loaded, "compression_enabled", False):
            from agentmux.integrations.compression import (
                inject_compression_env,
                start_compression_proxy,
            )

            port = start_compression_proxy(prepared.feature_dir)
            agents = inject_compression_env(agents, port)
        return self._launch_attached_session(
            args, prepared, agents, session_name=session_name
        )

    def _prepare_session(self, args, loaded) -> PreparedSession:
        if args.resume:
            if args.resume is True:
                selected = self.ui.select_session(
                    self.sessions.list_resumable_sessions()
                )
            else:
                selected = self.sessions.resolve_resume_target(str(args.resume))
            return self.sessions.prepare_resumed_session(selected)

        github = GitHubBootstrapper(
            self.project_dir, loaded.github, output=self.ui.print
        )
        issue_arg = getattr(args, "issue", None)
        if issue_arg:
            issue = github.resolve_issue(str(issue_arg))
            prompt = PromptInput(text=issue.prompt_text, slug_source=issue.slug_source)
            prepared = self.sessions.create(
                SessionCreateRequest(
                    prompt=prompt,
                    session_name=loaded.session_name,
                    feature_name=args.name,
                    product_manager=bool(args.product_manager),
                    gh_available=issue.gh_available,
                    issue_number=issue.issue_number,
                )
            )
        else:
            gh_available = github.detect_pr_availability()
            prompt = self.sessions.prompt_input_from_value(str(args.prompt))
            prepared = self.sessions.create(
                SessionCreateRequest(
                    prompt=prompt,
                    session_name=loaded.session_name,
                    feature_name=args.name,
                    product_manager=bool(args.product_manager),
                    gh_available=gh_available,
                )
            )

        # Create feature branch at startup for ALL sessions (not just --issue)
        branch_name = (
            f"{loaded.github.branch_prefix}"
            f"{feature_slug_from_dir(prepared.feature_dir)}"
        )
        git_manager = GitBranchManager(self.project_dir)
        branch_state = git_manager.ensure_branch(branch_name)

        if not branch_state.created:
            self.ui.print(
                f"Warning: Could not create/switch to feature branch {branch_name}; "
                "will retry at completion."
            )
        else:
            # Track branch info in session state
            from ..sessions.state_store import load_state, write_state

            state = load_state(prepared.files.state)
            state["feature_branch"] = branch_name
            state["branch_created"] = True
            write_state(prepared.files.state, state)

        return prepared

    def _post_attach_result(
        self, *, files, feature_dir: Path, elapsed_seconds: float = 0.0
    ) -> int:
        if not files.state.exists():
            if not feature_dir.exists():
                completion = _read_last_completion(self.project_dir)
                goodbye_success(
                    completion.get("feature_name")
                    or feature_slug_from_dir(feature_dir),
                    completion.get("commit_hash") or "",
                    completion.get("pr_url"),
                    completion.get("branch_name") or "",
                    elapsed_seconds,
                )
                return 0
            raise SystemExit(
                f"Session state missing after tmux exited: expected {files.state}. "
                "The feature directory still exists, so the session did not "
                "clean up successfully."
            )

        post_attach_state = load_state(files.state)
        if str(post_attach_state.get("phase")) == "failed":
            report = self.interruptions.report_from_state(
                post_attach_state, feature_dir, files=files
            )
            if report is None:
                report = self.interruptions.build_failed(
                    feature_dir,
                    "The pipeline ended in a failed state while the tmux session "
                    "was active.",
                    files=files,
                )
                self.interruptions.persist(files, report)
            return self._show_failure_screen(report, feature_dir)
        return 0

    def _cleanup_processes(
        self, feature_dir: Path, session_name: str, agents: dict[str, Any]
    ) -> None:
        """Kill all tracked processes for a session during error handling.

        This is a best-effort cleanup that silently ignores any errors.
        """
        try:
            runtime = self.runtime_factory.attach(
                feature_dir=feature_dir,
                project_dir=self.project_dir,
                session_name=session_name,
                agents=agents,
            )
            runtime.kill_tracked_processes(timeout=5.0)
        except Exception:
            pass  # Best effort cleanup

    def _launch_attached_session(
        self, args, prepared: PreparedSession, agents, session_name: str
    ) -> int:
        files = prepared.files
        feature_dir = prepared.feature_dir
        state = load_state(files.state)
        phase = str(state.get("phase", ""))
        initial_role = resolve_phase_startup_role(phase, feature_dir, state, agents)
        if initial_role is None:
            initial_role = (
                "product-manager"
                if phase == "product_management"
                and prepared.product_manager
                and "product-manager" in agents
                else "architect"
            )
        start_time = time.time()

        try:
            with (
                files.orchestrator_log.open("a", encoding="utf-8") as _setup_log,
                contextlib.redirect_stdout(_setup_log),
            ):
                self.runtime_factory.create(
                    feature_dir=feature_dir,
                    project_dir=self.project_dir,
                    session_name=session_name,
                    agents=agents,
                    config_path=self.config_path,
                    initial_role=initial_role,
                )
            self._start_background_orchestrator(feature_dir, args.keep_session)
            self.ui.print("agentmux: pipeline starting up…")
            subprocess.run(["tmux", "attach-session", "-t", session_name], check=True)
            return self._post_attach_result(
                files=files,
                feature_dir=feature_dir,
                elapsed_seconds=time.time() - start_time,
            )
        except KeyboardInterrupt:
            self._cleanup_processes(feature_dir, session_name, agents)
            report = self.interruptions.build_canceled(
                feature_dir,
                "The pipeline launcher received Ctrl-C.",
                files=files,
            )
            self.interruptions.persist(files, report)
            return self._show_failure_screen(report, feature_dir)
        except subprocess.CalledProcessError as exc:
            self._cleanup_processes(feature_dir, session_name, agents)
            if not files.state.exists():
                stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
                command = exc.cmd if isinstance(exc.cmd, list) else str(exc.cmd)
                raise SystemExit(f"Command failed: {command}\n{stderr}") from exc

            state = load_state(files.state)
            report = self.interruptions.report_from_state(
                state, feature_dir, files=files
            )
            if report is None:
                report = self.interruptions.build_failed(
                    feature_dir,
                    self.interruptions.summarize_subprocess_error(exc),
                    files=files,
                )
            self.interruptions.persist(files, report)
            return self._show_failure_screen(report, feature_dir)
        except Exception as exc:
            self._cleanup_processes(feature_dir, session_name, agents)
            if not files.state.exists():
                raise

            report = self.interruptions.build_failed(
                feature_dir,
                self.interruptions.summarize_exception(exc),
                files=files,
            )
            self.interruptions.persist(files, report)
            return self._show_failure_screen(report, feature_dir)

    def _show_failure_screen(self, report, feature_dir: Path) -> int:
        feature_name = feature_slug_from_dir(feature_dir)
        session_id = feature_dir.name
        if report.category == "canceled":
            goodbye_canceled(
                feature_name,
                session_id,
                report.resume_command,
                log_path=report.log_path,
            )
            return 130
        goodbye_error(
            feature_name,
            session_id,
            report.cause,
            resume_command=report.resume_command,
            log_path=report.log_path,
        )
        return 1

    def _start_background_orchestrator(
        self, feature_dir: Path, keep_session: bool
    ) -> None:
        command = [
            sys.executable,
            "-u",
            "-m",
            "agentmux.pipeline",
            "--orchestrate",
            str(feature_dir),
            "run",
        ]
        if self.config_path is not None:
            command.extend(["--config", str(self.config_path)])
        if keep_session:
            command.append("--keep-session")

        files = load_runtime_files(self.project_dir, feature_dir)
        log_handle = files.orchestrator_log.open("a", encoding="utf-8")
        child_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        subprocess.Popen(
            command,
            cwd=str(self.project_dir),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=child_env,
        )

    def _mcp_preparer(self) -> McpAgentPreparer:
        return McpAgentPreparer(
            self.project_dir,
            interactive=self.ui.is_interactive(),
            output=self.ui.stdout,
        )

    def run_sessions(self) -> int:
        """List all sessions with their phase, status, and updated timestamp."""
        sessions = self.sessions.list_resumable_sessions()
        active_tmux = list_agentmux_sessions()
        self.ui.print_session_list(sessions, active_tmux)
        return 0

    def run_clean(self, force: bool) -> int:
        """Remove all session directories and kill active tmux sessions."""
        sessions = self.sessions.list_resumable_sessions()
        count = len(sessions)

        if count == 0:
            self.ui.print("No sessions to remove.")
            return 0

        if not force and not self.ui.confirm_clean(count):
            return 0

        removed = self.sessions.remove_all_sessions(kill_tmux=True)
        self.ui.print(f"Removed {removed} session(s).")
        return 0

    def run_prompt(
        self, prompt, *, name=None, keep_session=False, product_manager=False
    ) -> int:
        self.ensure_dependencies()
        loaded = load_layered_config(
            self.project_dir, explicit_config_path=self.config_path
        )
        args = types.SimpleNamespace(
            prompt=prompt,
            name=name,
            keep_session=keep_session,
            product_manager=product_manager,
            resume=None,
            issue=None,
            orchestrate=None,
        )
        return self._run_launcher(args, loaded)

    def run_resume(self, session=None, *, keep_session=False) -> int:
        self.ensure_dependencies()
        loaded = load_layered_config(
            self.project_dir, explicit_config_path=self.config_path
        )
        args = types.SimpleNamespace(
            resume=session if session else True,
            issue=None,
            prompt=None,
            name=None,
            product_manager=False,
            orchestrate=None,
            keep_session=keep_session,
        )
        return self._run_launcher(args, loaded)

    def run_issue(
        self, number_or_url, *, name=None, keep_session=False, product_manager=False
    ) -> int:
        self.ensure_dependencies()
        loaded = load_layered_config(
            self.project_dir, explicit_config_path=self.config_path
        )
        args = types.SimpleNamespace(
            issue=number_or_url,
            resume=None,
            prompt=None,
            name=name,
            product_manager=product_manager,
            orchestrate=None,
            keep_session=keep_session,
        )
        return self._run_launcher(args, loaded)

    def run_orchestrate(self, feature_dir, *, keep_session=False) -> int:
        self.ensure_dependencies()
        loaded = load_layered_config(
            self.project_dir, explicit_config_path=self.config_path
        )
        args = types.SimpleNamespace(
            orchestrate=str(feature_dir), keep_session=keep_session
        )
        return self._run_background_orchestrator(args, loaded)
