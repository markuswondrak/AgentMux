#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any  # noqa: F401 — used by watchdog type stub

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - handled at runtime
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None

from src.config import LoadedConfig, load_explicit_config, load_layered_config
from src.models import AgentConfig
from src.phases import run_phase_cycle
from src.prompts import build_initial_prompts
from src.runtime import TmuxAgentRuntime
from src.state import (
    create_feature_files,
    infer_resume_phase,
    load_runtime_files,
    load_state,
    now_iso,
    update_phase,
    write_state,
)
from src.tmux import tmux_session_exists
from src.transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext

DEFAULT_CONFIG_HINT = ".agentmux/config.yaml"


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
    args = parser.parse_args()
    if not args.orchestrate and not args.prompt and not args.resume:
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
    return project_dir / ".multi-agent"


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
    if Observer is None:
        raise SystemExit(
            "Missing dependency: watchdog. Install it with `python3 -m pip install -r requirements.txt`."
        )


class FeatureEventHandler(FileSystemEventHandler):
    def __init__(self, wake_event: threading.Event) -> None:
        super().__init__()
        self.wake_event = wake_event

    def on_any_event(self, event: FileSystemEvent) -> None:
        if getattr(event, "is_directory", False):
            return
        self.wake_event.set()


def orchestrate(
    files,
    runtime: TmuxAgentRuntime,
    agents: dict[str, AgentConfig],
    max_review_iterations: int,
    keep_session: bool,
    product_manager: bool = False,
) -> int:
    _ = product_manager
    wake_event = threading.Event()
    observer = Observer()
    observer.schedule(
        FeatureEventHandler(wake_event), str(files.feature_dir), recursive=True
    )
    observer.start()

    ctx = PipelineContext(
        files=files,
        runtime=runtime,
        agents=agents,
        max_review_iterations=max_review_iterations,
        prompts=build_initial_prompts(files),
    )

    try:
        while True:
            wake_event.wait(timeout=1.0)
            wake_event.clear()
            state = load_state(files.state)
            result = run_phase_cycle(state, ctx)
            if result == EXIT_SUCCESS:
                return 0
            if result == EXIT_FAILURE:
                return 1
    finally:
        observer.stop()
        observer.join()
        runtime.shutdown(keep_session)


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
        str(Path(__file__).resolve()),
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
    args = parse_args()
    ensure_dependencies()
    config_path = Path(args.config).resolve() if args.config else None
    if args.orchestrate:
        project_dir = Path.cwd().resolve()
        loaded = load_runtime_config(project_dir, config_path)
        feature_dir = Path(args.orchestrate).resolve()
        files = load_runtime_files(project_dir, feature_dir)
        runtime = TmuxAgentRuntime.attach(
            feature_dir=feature_dir,
            session_name=loaded.session_name,
            agents=loaded.agents,
        )
        return orchestrate(
            files,
            runtime,
            loaded.agents,
            loaded.max_review_iterations,
            args.keep_session,
            args.product_manager,
        )

    project_dir = Path.cwd().resolve()
    loaded = load_runtime_config(project_dir, config_path)
    session_name = loaded.session_name
    agents = loaded.agents
    max_review_iterations = loaded.max_review_iterations

    if tmux_session_exists(session_name):
        raise SystemExit(
            f"tmux session `{session_name}` already exists. Stop it or change the resolved session name in your config."
        )

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
                in_multi_agent = multi_agent_root(project_dir) / resume_target
                if in_multi_agent.exists():
                    feature_dir = in_multi_agent.resolve()
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
        write_state(state_path, state)
    else:
        prompt_arg = args.prompt
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
        return 0
    except KeyboardInterrupt:
        update_phase(files.state, "failed", updated_by="pipeline", last_event="keyboard_interrupt")
        return 130
    except subprocess.CalledProcessError as exc:
        if runtime is not None:
            update_phase(files.state, "failed", updated_by="pipeline", last_event="subprocess_error")
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        command = exc.cmd if isinstance(exc.cmd, list) else str(exc.cmd)
        raise SystemExit(f"Command failed: {command}\n{stderr}") from exc
    except Exception:
        if runtime is not None and files.state.exists():
            update_phase(files.state, "failed", updated_by="pipeline", last_event="pipeline_exception")
        raise


if __name__ == "__main__":
    sys.exit(main())
