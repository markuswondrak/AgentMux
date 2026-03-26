#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .config import LoadedConfig, load_explicit_config, load_layered_config
from .event_bus import EventBus, SessionEvent, build_wake_listener
from .github import (
    check_gh_authenticated,
    check_gh_available,
    create_branch,
    extract_issue_number,
    fetch_issue,
)
from .interruption_events import (
    INTERRUPTION_CATEGORY_CANCELED,
    INTERRUPTION_CATEGORY_FAILED,
    canonical_event_for_category,
    canonical_interruption_event,
    fallback_cause_for_category,
    fallback_cause_from_event,
    interruption_category_from_event,
    interruption_title_for_category,
    normalize_interruption_category,
)
from .mcp_config import McpServerSpec, cleanup_mcp, ensure_mcp_config, setup_mcp
from .models import AgentConfig, GitHubConfig
from .phases import run_phase_cycle
from .prompts import build_initial_prompts
from .interruption_sources import INTERRUPTION_EVENT_PANE_EXITED, InterruptionEventSource
from .runtime import TmuxAgentRuntime
from .session_events import CreatedFilesLogListener, FileEventSource, ensure_watchdog_available
from .state import (
    create_feature_files,
    feature_slug_from_dir,
    infer_resume_phase,
    load_runtime_files,
    load_state,
    now_iso,
    update_phase,
    write_state,
)
from .tmux import tmux_session_exists
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext

DEFAULT_CONFIG_HINT = ".agentmux/config.yaml"
MCP_RESEARCH_ROLES = ("architect", "product-manager")


@dataclass(frozen=True)
class InterruptionReport:
    category: Literal["canceled", "failed"]
    cause: str
    resume_command: str
    log_path: str | None
    last_event: str


def _resume_command(feature_dir: Path) -> str:
    return f"agentmux --resume {shlex.quote(str(feature_dir))}"


def _log_path_if_available(files) -> str | None:
    log_path = files.orchestrator_log
    if log_path.exists():
        return str(log_path)
    return None


def _coalesce_text(value: Any) -> str:
    return " ".join(str(value).split()).strip()


def _report_from_state(state: dict[str, Any], feature_dir: Path, *, files=None) -> InterruptionReport | None:
    raw_category = normalize_interruption_category(state.get("interruption_category"))
    raw_cause = _coalesce_text(state.get("interruption_cause", ""))
    raw_resume = str(state.get("interruption_resume_command", "")).strip()
    raw_log_value = state.get("interruption_log_path")
    raw_log = None
    if isinstance(raw_log_value, str):
        raw_log = raw_log_value.strip() or None
    last_event = str(state.get("last_event", "")).strip()

    category: Literal["canceled", "failed"] | None = None
    if raw_category is not None:
        category = raw_category
    else:
        category = interruption_category_from_event(last_event)
    if category is None and state.get("phase") == "failed":
        category = INTERRUPTION_CATEGORY_FAILED

    if category is None:
        return None

    if not raw_cause:
        raw_cause = fallback_cause_from_event(last_event) if last_event else fallback_cause_for_category(category)
    if not raw_resume:
        raw_resume = _resume_command(feature_dir)
    if raw_log is None and files is not None:
        raw_log = _log_path_if_available(files)

    canonical_event = canonical_interruption_event(last_event) or canonical_event_for_category(category)
    return InterruptionReport(
        category=category,
        cause=raw_cause,
        resume_command=raw_resume,
        log_path=raw_log,
        last_event=canonical_event,
    )


def _build_report(
    *,
    feature_dir: Path,
    category: Literal["canceled", "failed"],
    cause: str,
    files=None,
) -> InterruptionReport:
    normalized_cause = _coalesce_text(cause) or fallback_cause_for_category(category)
    return InterruptionReport(
        category=category,
        cause=normalized_cause,
        resume_command=_resume_command(feature_dir),
        log_path=_log_path_if_available(files) if files is not None else None,
        last_event=canonical_event_for_category(category),
    )


def _persist_report(files, report: InterruptionReport) -> None:
    update_phase(
        files.state,
        "failed",
        updated_by="pipeline",
        last_event=report.last_event,
        interruption_category=report.category,
        interruption_cause=report.cause,
        interruption_resume_command=report.resume_command,
        interruption_log_path=report.log_path,
    )


def _format_report(report: InterruptionReport) -> str:
    title = interruption_title_for_category(report.category)
    lines = [
        title,
        f"Cause: {report.cause}",
        f"Resume: {report.resume_command}",
    ]
    if report.log_path:
        lines.append(f"Diagnostics log: {report.log_path}")
    return "\n".join(lines)


def _summarize_subprocess_error(exc: subprocess.CalledProcessError) -> str:
    command = exc.cmd if isinstance(exc.cmd, list) else [str(exc.cmd)]
    command_text = " ".join(str(part) for part in command if str(part).strip())
    stderr = _coalesce_text(exc.stderr or "")
    message = f"Command `{command_text}` failed with exit code {exc.returncode}."
    if stderr:
        message = f"{message} {stderr}"
    return message


def _summarize_exception(exc: Exception, *, context: str = "The pipeline crashed unexpectedly.") -> str:
    detail = _coalesce_text(str(exc))
    if detail:
        return f"{context} {exc.__class__.__name__}: {detail}"
    return f"{context} {exc.__class__.__name__}."


def parse_init_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agentmux init")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Run non-interactively with built-in defaults.",
    )
    return parser.parse_args(argv)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orchestrates a local tmux-based architect/coder/reviewer pipeline.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Feature description as free text, or path to a .md file.",
    )
    parser.add_argument(
        "--name",
        help="Optional feature slug. Defaults to timestamp plus a slug derived from the prompt.",
    )
    parser.add_argument(
        "--config",
        help=(
            "Optional config override. Without this flag the loader resolves "
            f"built-in defaults, ~/.config/agentmux/config.yaml, then {DEFAULT_CONFIG_HINT} "
            "or pipeline_config.json in the project."
        ),
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Keep the tmux session running after completion.",
    )
    parser.add_argument(
        "--product-manager",
        action="store_true",
        help="Enable product-management phase before planning.",
    )
    parser.add_argument(
        "--orchestrate",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const=True,
        default=None,
        help="Resume an interrupted pipeline session. Use with no value for interactive selection, or pass a feature dir/name.",
    )
    parser.add_argument(
        "--issue",
        help="GitHub issue number or URL to bootstrap requirements and slug.",
    )
    args = parser.parse_args()
    if not args.orchestrate and not args.prompt and not args.resume and not args.issue:
        parser.error("the following arguments are required: prompt")
    return args


def slugify(text: str, max_words: int = 8, max_length: int = 48) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = "-".join(words[:max_words]) or "feature"
    return slug[:max_length].strip("-") or "feature"


def load_config(path: Path) -> tuple[str, dict[str, AgentConfig], int]:
    loaded = load_explicit_config(path)
    return loaded.session_name, loaded.agents, loaded.max_review_iterations


def load_runtime_config(project_dir: Path, config_path: Path | None) -> LoadedConfig:
    return load_layered_config(project_dir, explicit_config_path=config_path)


def multi_agent_root(project_dir: Path) -> Path:
    return project_dir / ".agentmux" / ".sessions"


def list_resumable_sessions(project_dir: Path) -> list[tuple[Path, dict]]:
    root = multi_agent_root(project_dir)
    if not root.exists():
        return []

    sessions: list[tuple[Path, dict]] = []
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        state_path = candidate / "state.json"
        if not state_path.exists():
            continue
        sessions.append((candidate, load_state(state_path)))

    return sorted(
        sessions,
        key=lambda item: str(item[1].get("updated_at", "")),
        reverse=True,
    )


def select_session(sessions: list[tuple[Path, dict]]) -> Path:
    if not sessions:
        raise SystemExit("No resumable sessions found.")

    if len(sessions) == 1:
        feature_dir, state = sessions[0]
        print(
            "Auto-selected resumable session: "
            f"{feature_dir.name} (phase: {state.get('phase', 'unknown')})"
        )
        return feature_dir

    print("Resumable sessions:")
    for index, (feature_dir, state) in enumerate(sessions, start=1):
        phase = state.get("phase", "unknown")
        last_event = state.get("last_event", "n/a")
        updated_at = str(state.get("updated_at", "n/a"))
        updated_label = updated_at[:16].replace("T", " ") if updated_at != "n/a" else "n/a"
        print(
            f"  {index}) {feature_dir.name:<36} "
            f"phase: {phase:<12} last_event: {last_event} (updated: {updated_label})"
        )

    while True:
        choice = input(f"Select session [1-{len(sessions)}]: ").strip()
        if not choice.isdigit():
            print("Invalid selection. Enter a number.")
            continue
        session_index = int(choice)
        if 1 <= session_index <= len(sessions):
            return sessions[session_index - 1][0]
        print("Invalid selection. Try again.")


def ensure_dependencies() -> None:
    ensure_watchdog_available()
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: mcp. Install it with `python3 -m pip install -r requirements.txt`."
        ) from exc


def orchestrate(
    files,
    runtime: TmuxAgentRuntime,
    agents: dict[str, AgentConfig],
    max_review_iterations: int,
    keep_session: bool,
    product_manager: bool = False,
    github_config: GitHubConfig | None = None,
) -> int:
    _ = product_manager
    wake_event = threading.Event()
    event_bus = build_orchestrator_event_bus(files, runtime, wake_event)
    pending_interruption: dict[str, Any] | None = None
    interruption_lock = threading.Lock()

    def _handle_interruption(event: SessionEvent) -> None:
        nonlocal pending_interruption
        if event.kind != INTERRUPTION_EVENT_PANE_EXITED:
            return
        with interruption_lock:
            if pending_interruption is None:
                pending_interruption = dict(event.payload)
        wake_event.set()

    event_bus.register(_handle_interruption)
    event_bus.start()

    try:
        ctx = PipelineContext(
            files=files,
            runtime=runtime,
            agents=agents,
            max_review_iterations=max_review_iterations,
            prompts=build_initial_prompts(files),
            github_config=github_config or GitHubConfig(),
        )
        while True:
            wake_event.wait(timeout=1.0)
            wake_event.clear()
            with interruption_lock:
                interruption = pending_interruption
            if interruption is not None:
                report = _build_report(
                    feature_dir=files.feature_dir,
                    category=INTERRUPTION_CATEGORY_CANCELED,
                    cause=str(interruption.get("message", "")).strip() or "An agent pane exited unexpectedly.",
                    files=files,
                )
                _persist_report(files, report)
                return 130
            state = load_state(files.state)
            result = run_phase_cycle(state, ctx)
            if result == EXIT_SUCCESS:
                return 0
            if result == EXIT_FAILURE:
                return 1
    finally:
        try:
            event_bus.stop()
        finally:
            try:
                cleanup_mcp(files.feature_dir, files.project_dir)
            finally:
                runtime.shutdown(keep_session)


def build_orchestrator_event_bus(
    files,
    runtime: TmuxAgentRuntime,
    wake_event: threading.Event,
) -> EventBus:
    bus = EventBus(
        sources=[
            FileEventSource(files.feature_dir),
            InterruptionEventSource(runtime),
        ]
    )
    bus.register(build_wake_listener(wake_event))
    bus.register(CreatedFilesLogListener(files.created_files_log).handle_event)
    return bus


def start_background_orchestrator(
    config_path: Path | None,
    project_dir: Path,
    feature_dir: Path,
    keep_session: bool,
    product_manager: bool = False,
) -> None:
    command = [
        sys.executable,
        "-u",
        "-m",
        "agentmux.pipeline",
        "--orchestrate",
        str(feature_dir),
    ]
    if config_path is not None:
        command.extend(["--config", str(config_path)])
    if keep_session:
        command.append("--keep-session")
    if product_manager:
        command.append("--product-manager")

    files = load_runtime_files(project_dir, feature_dir)
    log_handle = files.orchestrator_log.open("a", encoding="utf-8")
    subprocess.Popen(
        command,
        cwd=str(project_dir),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        from .init import run_init

        init_args = parse_init_args(sys.argv[2:])
        return run_init(defaults_mode=bool(init_args.defaults))

    args = parse_args()
    ensure_dependencies()
    config_path = Path(args.config).resolve() if args.config else None
    if args.orchestrate:
        project_dir = Path.cwd().resolve()
        loaded = load_runtime_config(project_dir, config_path)
        feature_dir = Path(args.orchestrate).resolve()
        mcp_servers = [
            McpServerSpec(
                name="agentmux-research",
                module="agentmux.mcp_research_server",
                env={},
            )
        ]
        agents = setup_mcp(
            loaded.agents,
            mcp_servers,
            MCP_RESEARCH_ROLES,
            feature_dir,
            project_dir,
        )
        files = load_runtime_files(project_dir, feature_dir)
        runtime = TmuxAgentRuntime.attach(
            feature_dir=feature_dir,
            session_name=loaded.session_name,
            agents=agents,
        )
        try:
            return orchestrate(
                files,
                runtime,
                agents,
                loaded.max_review_iterations,
                args.keep_session,
                args.product_manager,
                github_config=loaded.github,
            )
        except KeyboardInterrupt:
            report = _build_report(
                feature_dir=feature_dir,
                category=INTERRUPTION_CATEGORY_CANCELED,
                cause="The background orchestrator received Ctrl-C.",
                files=files,
            )
            _persist_report(files, report)
            print(_format_report(report))
            return 130
        except Exception as exc:
            report = _build_report(
                feature_dir=feature_dir,
                category=INTERRUPTION_CATEGORY_FAILED,
                cause=_summarize_exception(exc, context="The background orchestrator crashed unexpectedly."),
                files=files,
            )
            _persist_report(files, report)
            print(_format_report(report))
            return 1

    project_dir = Path.cwd().resolve()
    loaded = load_runtime_config(project_dir, config_path)
    session_name = loaded.session_name
    agents = loaded.agents
    max_review_iterations = loaded.max_review_iterations
    issue_arg = getattr(args, "issue", None)

    if args.resume and issue_arg:
        raise SystemExit("--issue cannot be used with --resume.")

    if tmux_session_exists(session_name):
        raise SystemExit(
            f"tmux session `{session_name}` already exists. Stop it or change the resolved session name in your config."
        )

    ensure_mcp_config(
        agents,
        [McpServerSpec(name="agentmux-research", module="agentmux.mcp_research_server", env={})],
        MCP_RESEARCH_ROLES,
        project_dir,
        interactive=sys.stdin.isatty(),
        output=sys.stdout,
    )

    issue_payload: dict[str, str] | None = None
    issue_number: str | None = None

    gh_available: bool | None = None
    if not args.resume:
        if issue_arg:
            if not check_gh_available():
                raise SystemExit("gh CLI is required for --issue. Install: https://cli.github.com")
            if not check_gh_authenticated():
                raise SystemExit("gh is not authenticated. Run: gh auth login")
            try:
                issue_number = extract_issue_number(str(issue_arg))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            try:
                issue_payload = fetch_issue(str(issue_arg))
            except RuntimeError as exc:
                raise SystemExit(str(exc)) from exc
            gh_available = True
            try:
                subprocess.run(
                    ["git", "pull", "origin", loaded.github.base_branch],
                    cwd=project_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                print(f"Pulled latest from origin/{loaded.github.base_branch}.")
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
                print(f"Warning: could not pull origin/{loaded.github.base_branch}: {stderr}")
        else:
            gh_available = check_gh_available() and check_gh_authenticated()
            if not gh_available:
                print("Warning: gh CLI not available or not authenticated. PR creation will be skipped.")

    runtime: TmuxAgentRuntime | None = None
    files = None

    if args.resume:
        if args.resume is True:
            feature_dir = select_session(list_resumable_sessions(project_dir))
        else:
            resume_target = Path(str(args.resume))
            if resume_target.is_absolute():
                feature_dir = resume_target.resolve()
            else:
                in_session_root = multi_agent_root(project_dir) / resume_target
                if in_session_root.exists():
                    feature_dir = in_session_root.resolve()
                else:
                    feature_dir = (project_dir / resume_target).resolve()
        if not feature_dir.exists():
            raise SystemExit(f"Feature directory not found: {feature_dir}")
        state_path = feature_dir / "state.json"
        if not state_path.exists():
            raise SystemExit(f"No state.json found in {feature_dir}")

        files = load_runtime_files(project_dir, feature_dir)
        state = load_state(state_path)
        state["phase"] = infer_resume_phase(feature_dir, state)
        state["last_event"] = "resumed"
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        for key in (
            "interruption_category",
            "interruption_cause",
            "interruption_resume_command",
            "interruption_log_path",
        ):
            state.pop(key, None)
        write_state(state_path, state)
    else:
        if issue_payload is not None:
            prompt_text = issue_payload["body"].strip() or issue_payload["title"]
            slug_source = issue_payload["title"]
        else:
            prompt_arg = str(args.prompt)
            prompt_path = Path(prompt_arg)
            prompt_is_md_file = prompt_arg.endswith(".md") and prompt_path.is_file()
            if prompt_is_md_file:
                prompt_text = prompt_path.read_text(encoding="utf-8")
                slug_source = prompt_path.stem
            else:
                prompt_text = prompt_arg
                slug_source = prompt_arg

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        feature_name = args.name or f"{timestamp}-{slugify(slug_source)}"
        feature_dir = multi_agent_root(project_dir) / feature_name
        files = create_feature_files(
            project_dir,
            feature_dir,
            prompt_text,
            session_name,
            product_manager=bool(args.product_manager),
        )
        state = load_state(files.state)
        state["gh_available"] = bool(gh_available)
        if issue_number is not None:
            state["issue_number"] = issue_number
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(files.state, state)

        if issue_arg and gh_available:
            branch_name = f"{loaded.github.branch_prefix}{feature_slug_from_dir(feature_dir)}"
            if not create_branch(project_dir, branch_name):
                print("Warning: Could not create feature branch now; will retry at completion.")

    mcp_servers = [
        McpServerSpec(
            name="agentmux-research",
            module="agentmux.mcp_research_server",
            env={},
        )
    ]
    agents = setup_mcp(
        agents,
        mcp_servers,
        MCP_RESEARCH_ROLES,
        feature_dir,
        project_dir,
    )

    current_state = load_state(files.state)
    pm_active = bool(current_state.get("product_manager"))
    initial_role = "product-manager" if pm_active and "product-manager" in agents else "architect"

    try:
        runtime = TmuxAgentRuntime.create(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
            config_path=config_path,
            initial_role=initial_role,
        )
        start_background_orchestrator(
            config_path,
            project_dir,
            feature_dir,
            args.keep_session,
            product_manager=pm_active,
        )
        print(f"Feature directory: {feature_dir}")
        print(f"tmux session: {session_name}")
        subprocess.run(["tmux", "attach-session", "-t", session_name], check=True)
        post_attach_state = load_state(files.state)
        if str(post_attach_state.get("phase")) == "failed":
            report = _report_from_state(post_attach_state, feature_dir, files=files)
            if report is None:
                report = _build_report(
                    feature_dir=feature_dir,
                    category=INTERRUPTION_CATEGORY_FAILED,
                    cause="The pipeline ended in a failed state while the tmux session was active.",
                    files=files,
                )
                _persist_report(files, report)
            print(_format_report(report))
            return 130 if report.category == INTERRUPTION_CATEGORY_CANCELED else 1
        return 0
    except KeyboardInterrupt:
        report = _build_report(
            feature_dir=feature_dir,
            category=INTERRUPTION_CATEGORY_CANCELED,
            cause="The pipeline launcher received Ctrl-C.",
            files=files,
        )
        _persist_report(files, report)
        print(_format_report(report))
        return 130
    except subprocess.CalledProcessError as exc:
        if files is None or not files.state.exists():
            stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
            command = exc.cmd if isinstance(exc.cmd, list) else str(exc.cmd)
            raise SystemExit(f"Command failed: {command}\n{stderr}") from exc

        state = load_state(files.state)
        report = _report_from_state(state, feature_dir, files=files)
        if report is None:
            report = _build_report(
                feature_dir=feature_dir,
                category=INTERRUPTION_CATEGORY_FAILED,
                cause=_summarize_subprocess_error(exc),
                files=files,
            )
        _persist_report(files, report)
        print(_format_report(report))
        return 130 if report.category == INTERRUPTION_CATEGORY_CANCELED else 1
    except Exception as exc:
        if files is None or not files.state.exists():
            raise

        report = _build_report(
            feature_dir=feature_dir,
            category=INTERRUPTION_CATEGORY_FAILED,
            cause=_summarize_exception(exc),
            files=files,
        )
        _persist_report(files, report)
        print(_format_report(report))
        return 1


if __name__ == "__main__":
    sys.exit(main())
