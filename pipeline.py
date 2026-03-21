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

from src.handlers import (
    guard_design_ready,
    guard_coders_done,
    guard_plan_ready_design,
    guard_plan_ready_multi,
    guard_plan_ready_single,
    guard_review_fail,
    guard_review_pass_docs,
    guard_review_pass_no_docs,
    handle_changes_requested,
    handle_coders_done,
    handle_completion_approved,
    handle_design_ready,
    handle_docs_done,
    handle_failed,
    handle_plan_ready_design,
    handle_plan_ready_multi,
    handle_plan_ready_single,
    handle_review_fail,
    handle_review_pass_docs,
    handle_review_pass_no_docs,
    handle_start_review,
)
from src.models import AgentConfig
from src.prompts import build_all_prompts
from src.state import (
    create_feature_files,
    load_runtime_files,
    load_state,
    update_state,
)
from src.tmux import (
    send_prompt,
    tmux_kill_session,
    tmux_new_session,
    tmux_session_exists,
)
from src.transitions import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    PipelineContext,
    Transition,
    dispatch,
    not_handled,
)

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


TRANSITIONS = [
    Transition("plan_ready", guard_plan_ready_design, handle_plan_ready_design,
               "plan_ready -> designer_requested"),
    Transition("design_ready", guard_design_ready, handle_design_ready,
               "design_ready -> plan_ready (coder handoff)"),
    Transition("plan_ready", guard_plan_ready_multi, handle_plan_ready_multi,
               "plan_ready -> coders_requested (parallel)"),
    Transition("plan_ready", guard_plan_ready_single, handle_plan_ready_single,
               "plan_ready -> coder_requested (single)"),
    Transition("coders_requested", guard_coders_done, handle_coders_done,
               "coders_requested -> implementation_done"),
    Transition("implementation_done", not_handled, handle_start_review,
               "implementation_done -> review_requested"),
    Transition("review_ready", guard_review_fail, handle_review_fail,
               "review_ready -> fix_requested"),
    Transition("review_ready", guard_review_pass_docs, handle_review_pass_docs,
               "review_ready -> docs_update_requested"),
    Transition("review_ready", guard_review_pass_no_docs, handle_review_pass_no_docs,
               "review_ready -> completion_pending"),
    Transition("docs_updated", not_handled, handle_docs_done,
               "docs_updated -> completion_pending"),
    Transition("changes_requested", not_handled, handle_changes_requested,
               "changes_requested -> architect_requested"),
    Transition("completion_approved", lambda s, c: True, handle_completion_approved,
               "completion_approved -> exit"),
    Transition("failed", lambda s, c: True, handle_failed,
               "failed -> exit"),
]


def _save_panes(
    feature_dir: Path,
    panes: dict[str, str | None],
    coder_panes: dict[int, str] | None = None,
) -> None:
    """Persist current pane mapping for the control pane monitor."""
    data = dict(panes)
    if coder_panes:
        for idx, pane_id in coder_panes.items():
            data[f"coder_{idx}"] = pane_id
    target = feature_dir / "panes.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.rename(target)


def orchestrate(
    files,
    panes: dict[str, str | None],
    agents: dict[str, AgentConfig],
    max_review_iterations: int,
    keep_session: bool,
    session_name: str,
) -> int:
    wake_event = threading.Event()
    observer = Observer()
    observer.schedule(
        FeatureEventHandler(wake_event), str(files.feature_dir), recursive=False
    )
    observer.start()

    ctx = PipelineContext(
        files=files,
        panes=panes,
        coder_panes={},
        agents=agents,
        max_review_iterations=max_review_iterations,
        session_name=session_name,
        prompts=build_all_prompts(files),
    )

    send_prompt(panes["architect"], ctx.prompts["architect"])

    try:
        while True:
            wake_event.wait(timeout=1.0)
            wake_event.clear()
            state = load_state(files.state)
            _save_panes(files.feature_dir, ctx.panes, ctx.coder_panes)

            result = dispatch(state, TRANSITIONS, ctx)
            if result == EXIT_SUCCESS:
                return 0
            if result == EXIT_FAILURE:
                return 1
    finally:
        observer.stop()
        observer.join()
        if not keep_session:
            tmux_kill_session(session_name)


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
        panes_file = feature_dir / "panes.json"
        if panes_file.exists():
            panes = json.loads(panes_file.read_text(encoding="utf-8"))
            panes.setdefault("coder", None)
            panes.setdefault("docs", None)
            panes.setdefault("designer", None)
        else:
            panes: dict[str, str | None] = {
                "architect": f"{session_name}:0.0",
                "coder": None,
                "docs": None,
                "designer": None,
            }
        return orchestrate(
            files, panes, agents, max_review_iterations, args.keep_session, session_name
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

    panes: dict[str, str | None] | None = None
    try:
        panes = tmux_new_session(
            session_name, agents["architect"], feature_dir, config_path
        )
        panes["docs"] = None
        panes["designer"] = None
        _save_panes(feature_dir, panes)
        start_background_orchestrator(
            config_path, project_dir, feature_dir, args.keep_session
        )
        print(f"Feature directory: {feature_dir}")
        print(f"tmux session: {session_name}")
        subprocess.run(["tmux", "attach-session", "-t", session_name], check=True)
        return 0
    except KeyboardInterrupt:
        update_state(
            files.state, "failed", updated_by="pipeline", active_role="pipeline"
        )
        return 130
    except subprocess.CalledProcessError as exc:
        if panes is not None:
            update_state(
                files.state, "failed", updated_by="pipeline", active_role="pipeline"
            )
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        command = exc.cmd if isinstance(exc.cmd, list) else str(exc.cmd)
        raise SystemExit(f"Command failed: {command}\n{stderr}") from exc
    except Exception:
        if panes is not None and files.state.exists():
            update_state(
                files.state, "failed", updated_by="pipeline", active_role="pipeline"
            )
        raise


if __name__ == "__main__":
    sys.exit(main())
