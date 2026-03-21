#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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

from src.models import AgentConfig
from src.phases import run_phase_cycle
from src.prompts import build_initial_prompts
from src.runtime import TmuxAgentRuntime
from src.state import (
    create_feature_files,
    load_runtime_files,
    load_state,
    update_phase,
)
from src.tmux import tmux_session_exists
from src.transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "pipeline_config.json"


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
        default=str(CONFIG_PATH),
        help=f"Path to the pipeline config JSON file. Default: {CONFIG_PATH.name}",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Keep the tmux session running after completion.",
    )
    parser.add_argument(
        "--orchestrate",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if not args.orchestrate and not args.prompt:
        parser.error("the following arguments are required: prompt")
    return args


def slugify(text: str, max_words: int = 8, max_length: int = 48) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = "-".join(words[:max_words]) or "feature"
    return slug[:max_length].strip("-") or "feature"


def load_config(path: Path) -> tuple[str, dict[str, AgentConfig], int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    session_name = raw["session_name"]
    max_review_iterations = int(raw.get("max_review_iterations", 3))
    agents = {
        "architect": AgentConfig(
            role="architect",
            cli=raw["architect"]["cli"],
            model=raw["architect"]["model"],
            args=raw["architect"].get("args", []),
        ),
        "coder": AgentConfig(
            role="coder",
            cli=raw["coder"]["cli"],
            model=raw["coder"]["model"],
            args=raw["coder"].get("args", []),
        ),
    }
    docs_raw = raw.get("docs")
    if docs_raw:
        agents["docs"] = AgentConfig(
            role="docs",
            cli=docs_raw["cli"],
            model=docs_raw["model"],
            args=docs_raw.get("args", []),
        )
    designer_raw = raw.get("designer")
    if designer_raw:
        agents["designer"] = AgentConfig(
            role="designer",
            cli=designer_raw["cli"],
            model=designer_raw["model"],
            args=designer_raw.get("args", []),
        )
    return session_name, agents, max_review_iterations


def multi_agent_root(project_dir: Path) -> Path:
    return project_dir / ".multi-agent"


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
) -> int:
    wake_event = threading.Event()
    observer = Observer()
    observer.schedule(
        FeatureEventHandler(wake_event), str(files.feature_dir), recursive=False
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
    config_path: Path, project_dir: Path, feature_dir: Path, keep_session: bool
) -> None:
    command = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        "--config",
        str(config_path),
        "--orchestrate",
        str(feature_dir),
    ]
    if keep_session:
        command.append("--keep-session")

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
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    session_name, agents, max_review_iterations = load_config(config_path)
    if args.orchestrate:
        project_dir = Path.cwd().resolve()
        feature_dir = Path(args.orchestrate).resolve()
        files = load_runtime_files(project_dir, feature_dir)
        runtime = TmuxAgentRuntime.attach(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
        )
        return orchestrate(
            files, runtime, agents, max_review_iterations, args.keep_session
        )

    if tmux_session_exists(session_name):
        raise SystemExit(
            f"tmux session `{session_name}` already exists. Stop it or change `session_name` in {config_path}."
        )

    project_dir = Path.cwd().resolve()
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
    files = create_feature_files(project_dir, feature_dir, prompt_text, session_name)

    runtime: TmuxAgentRuntime | None = None
    try:
        runtime = TmuxAgentRuntime.create(
            feature_dir=feature_dir,
            session_name=session_name,
            agents=agents,
            config_path=config_path,
        )
        start_background_orchestrator(
            config_path, project_dir, feature_dir, args.keep_session
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
