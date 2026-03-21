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
from typing import Any

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - handled at runtime
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None

from src.models import AgentConfig
from src.plan_parser import split_plan_into_subplans
from src.prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_coder_prompt,
    build_coder_subplan_prompt,
    build_confirmation_prompt,
    build_docs_prompt,
    build_fix_prompt,
    write_prompt_file,
)
from src.state import (
    cleanup_feature_dir,
    commit_changes,
    create_feature_files,
    load_runtime_files,
    load_state,
    now_iso,
    parse_review_verdict,
    update_state,
    write_state,
)
from src.tmux import (
    create_agent_pane,
    kill_agent_pane,
    send_prompt,
    tmux_kill_session,
    tmux_new_session,
    tmux_pane_exists,
    tmux_session_exists,
)

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "pipeline_config.json"
FINAL_STATES = {"completion_approved", "failed"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orchestrates a local tmux-based architect/coder/reviewer pipeline.",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Feature description as free text.",
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

    architect_prompt = write_prompt_file(
        files.feature_dir,
        "architect_prompt.md",
        build_architect_prompt(files, state_target="plan_ready"),
    )
    coder_prompt = write_prompt_file(
        files.feature_dir,
        "coder_prompt.md",
        build_coder_prompt(files, state_target="implementation_done"),
    )
    review_prompt = write_prompt_file(
        files.feature_dir,
        "review_prompt.md",
        build_architect_prompt(files, state_target="review_ready", is_review=True),
    )
    confirmation_prompt = write_prompt_file(
        files.feature_dir,
        "confirmation_prompt.md",
        build_confirmation_prompt(
            files,
            approved_target="completion_approved",
            changes_target="changes_requested",
        ),
    )

    coder_dispatched = False
    coders_dispatched = False
    review_dispatched = False
    docs_dispatched = False
    confirmation_dispatched = False
    change_reroute_dispatched = False
    coder_panes: dict[int, str] = {}
    send_prompt(panes["architect"], architect_prompt)

    try:
        while True:
            wake_event.wait(timeout=1.0)
            wake_event.clear()
            state = load_state(files.state)
            status = state.get("status")

            # Keep panes.json in sync so the control pane monitor can track active agents
            _save_panes(files.feature_dir, panes, coder_panes)

            if (
                status == "plan_ready"
                and not coder_dispatched
                and not coders_dispatched
            ):
                for done_marker in files.feature_dir.glob("done_*"):
                    if done_marker.is_file():
                        done_marker.unlink()

                subplan_paths = split_plan_into_subplans(files.plan, files.feature_dir)
                subplan_count = len(subplan_paths)

                if subplan_count > 1:
                    for subplan_index, subplan_path in enumerate(
                        subplan_paths, start=1
                    ):
                        pane_id = create_agent_pane(session_name, "coder", agents)
                        coder_panes[subplan_index] = pane_id
                        subplan_prompt = write_prompt_file(
                            files.feature_dir,
                            f"coder_prompt_{subplan_index}.txt",
                            build_coder_subplan_prompt(
                                files,
                                subplan_path=subplan_path,
                                subplan_index=subplan_index,
                                state_target="implementation_done",
                            ),
                        )
                        send_prompt(pane_id, subplan_prompt)

                    state["status"] = "coders_requested"
                    state["subplan_count"] = subplan_count
                    state["updated_at"] = now_iso()
                    state["updated_by"] = "pipeline"
                    state["active_role"] = "coder"
                    write_state(files.state, state)
                    coders_dispatched = True
                else:
                    if not tmux_pane_exists(panes["coder"]):
                        panes["coder"] = create_agent_pane(
                            session_name, "coder", agents
                        )
                    state["status"] = "coder_requested"
                    state["subplan_count"] = 1
                    state["updated_at"] = now_iso()
                    state["updated_by"] = "pipeline"
                    state["active_role"] = "coder"
                    write_state(files.state, state)
                    send_prompt(panes["coder"], coder_prompt)
                    coder_dispatched = True
                continue

            if status == "coders_requested" and coders_dispatched:
                expected_count = int(state.get("subplan_count", 0))
                if expected_count <= 0:
                    expected_count = len(coder_panes)
                if expected_count > 0 and all(
                    (files.feature_dir / f"done_{idx}").exists()
                    for idx in range(1, expected_count + 1)
                ):
                    for pane_id in coder_panes.values():
                        kill_agent_pane(pane_id)
                    coder_panes.clear()
                    state["status"] = "implementation_done"
                    state["updated_at"] = now_iso()
                    state["updated_by"] = "pipeline"
                    state["active_role"] = "architect"
                    write_state(files.state, state)
                continue

            if status == "implementation_done" and not review_dispatched:
                update_state(
                    files.state,
                    "review_requested",
                    updated_by="pipeline",
                    active_role="architect",
                )
                send_prompt(panes["architect"], review_prompt)
                review_dispatched = True
                continue

            if status == "review_ready" and not docs_dispatched:
                review_text = files.review.read_text(encoding="utf-8")
                verdict = parse_review_verdict(review_text)
                review_iteration = int(state.get("review_iteration", 0))

                if verdict == "fail" and review_iteration < max_review_iterations:
                    for pane_id in coder_panes.values():
                        kill_agent_pane(pane_id)
                    coder_panes.clear()
                    files.fix_request.write_text(review_text, encoding="utf-8")
                    state["review_iteration"] = review_iteration + 1
                    state["status"] = "fix_requested"
                    state["subplan_count"] = 1
                    state["updated_at"] = now_iso()
                    state["updated_by"] = "pipeline"
                    state["active_role"] = "coder"
                    write_state(files.state, state)
                    if not tmux_pane_exists(panes["coder"]):
                        panes["coder"] = create_agent_pane(
                            session_name, "coder", agents
                        )
                    fix_prompt = write_prompt_file(
                        files.feature_dir,
                        "fix_prompt.txt",
                        build_fix_prompt(files, state_target="implementation_done"),
                    )
                    send_prompt(panes["coder"], fix_prompt)
                    review_dispatched = False
                    confirmation_dispatched = False
                    continue

                kill_agent_pane(panes["coder"])
                panes["coder"] = None
                if verdict is None:
                    print(
                        "Warning: parse_review_verdict returned None — treating as pass and requesting docs update"
                    )
                if "docs" in agents:
                    update_state(
                        files.state,
                        "docs_update_requested",
                        updated_by="pipeline",
                        active_role="docs",
                    )
                    panes["docs"] = create_agent_pane(session_name, "docs", agents)
                    docs_prompt = write_prompt_file(
                        files.feature_dir,
                        "docs_prompt.txt",
                        build_docs_prompt(files, state_target="docs_updated"),
                    )
                    send_prompt(panes["docs"], docs_prompt)
                    docs_dispatched = True
                else:
                    update_state(
                        files.state,
                        "completion_pending",
                        updated_by="pipeline",
                        active_role="architect",
                    )
                    send_prompt(panes["architect"], confirmation_prompt)
                    confirmation_dispatched = True
                continue

            if status == "docs_updated" and not confirmation_dispatched:
                kill_agent_pane(panes["docs"])
                panes["docs"] = None
                update_state(
                    files.state,
                    "completion_pending",
                    updated_by="pipeline",
                    active_role="architect",
                )
                send_prompt(panes["architect"], confirmation_prompt)
                confirmation_dispatched = True
                continue

            if status == "changes_requested" and not change_reroute_dispatched:
                kill_agent_pane(panes["coder"])
                panes["coder"] = None
                kill_agent_pane(panes["docs"])
                panes["docs"] = None
                for pane_id in coder_panes.values():
                    kill_agent_pane(pane_id)
                coder_panes.clear()
                change_reroute_dispatched = True
                changes_prompt = write_prompt_file(
                    files.feature_dir,
                    "changes_prompt.txt",
                    build_change_prompt(files, state_target="plan_ready"),
                )
                send_prompt(panes["architect"], changes_prompt)
                state["status"] = "architect_requested"
                state["subplan_count"] = 0
                state["review_iteration"] = 0
                state["updated_at"] = now_iso()
                state["updated_by"] = "pipeline"
                state["active_role"] = "architect"
                write_state(files.state, state)
                coder_dispatched = False
                coders_dispatched = False
                review_dispatched = False
                docs_dispatched = False
                confirmation_dispatched = False
                change_reroute_dispatched = False
                continue

            if status in FINAL_STATES:
                if status == "completion_approved":
                    commit_message = str(state.get("commit_message", "")).strip()
                    raw_commit_files = state.get("commit_files", [])
                    commit_files = (
                        [
                            str(path).strip()
                            for path in raw_commit_files
                            if str(path).strip()
                        ]
                        if isinstance(raw_commit_files, list)
                        else []
                    )
                    commit_hash = commit_changes(
                        files.project_dir, commit_message, commit_files
                    )
                    if commit_hash is not None:
                        print("Completion approved and commit created.")
                        print(f"Commit message: {commit_message}")
                        print(f"Commit hash: {commit_hash}")
                        print("Committed files:")
                        for file_path in commit_files:
                            print(f"- {file_path}")
                    else:
                        print(
                            "Completion approved, but commit step failed or was skipped."
                        )
                    cleanup_feature_dir(files.feature_dir)
                    return 0
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
        else:
            panes: dict[str, str | None] = {
                "architect": f"{session_name}:0.0",
                "coder": None,
                "docs": None,
            }
        return orchestrate(
            files, panes, agents, max_review_iterations, args.keep_session, session_name
        )

    if tmux_session_exists(session_name):
        raise SystemExit(
            f"tmux session `{session_name}` already exists. Stop it or change `session_name` in {config_path}."
        )

    project_dir = Path.cwd().resolve()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    feature_name = args.name or f"{timestamp}-{slugify(args.prompt)}"
    feature_dir = multi_agent_root(project_dir) / feature_name
    files = create_feature_files(project_dir, feature_dir, args.prompt, session_name)

    panes: dict[str, str | None] | None = None
    try:
        panes = tmux_new_session(
            session_name, agents["architect"], feature_dir, config_path
        )
        panes["docs"] = None
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
