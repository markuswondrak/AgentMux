#!/usr/bin/env python3
"""Control pane monitor for the multi-agent pipeline."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from ..configuration import infer_project_dir, load_layered_config
from ..sessions.state_store import load_runtime_files
from ..shared.models import RuntimeFiles
from ..terminal_ui.layout import MONITOR_WIDTH
from . import render as render_module  # noqa: F401
from .render import _ANSI_RE as _ANSI_RE
from .render import RESET as RESET
from .render import WHITE as WHITE
from .render import Monitor as Monitor
from .state_reader import PIPELINE_STATES as PIPELINE_STATES
from .state_reader import get_role_states as get_role_states
from .state_reader import load_state
from .state_reader import tmux_session_exists as tmux_session_exists


def render(
    session_name: str,
    files: RuntimeFiles,
    agents: dict[str, dict[str, str]],
    width: int,
    height: int,
    start_time: float,
    log_path: Path | None = None,
) -> str:
    """Render a monitor frame for the given session state."""
    mon = Monitor(session_name, files, agents)
    mon._start_time = start_time
    return mon.render(width, height)


def append_status_change(
    log_path: Path, prev_status: str | None, status: str
) -> str | None:
    if not status:
        return prev_status
    if status == prev_status:
        return prev_status

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{ts}  {status}\n")
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-dir", required=True)
    parser.add_argument("--session-name", required=True)
    parser.add_argument("--config")
    args = parser.parse_args()

    feature_dir = Path(args.feature_dir)
    project_dir = infer_project_dir(feature_dir)
    files = load_runtime_files(project_dir, feature_dir)

    config_path = Path(args.config).resolve() if args.config else None

    loaded = load_layered_config(
        project_dir,
        explicit_config_path=config_path,
    )
    agents = {
        role: {"cli": agent.cli, "model": agent.model}
        for role, agent in loaded.agents.items()
    }

    monitor = Monitor(args.session_name, files, agents)
    prev_status: str | None = None
    session_lost_count = 0

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            # Check whether the tmux session still exists
            if not tmux_session_exists(args.session_name):
                session_lost_count += 1
                # Give it 2 consecutive failures to avoid race conditions
                # during session teardown
                if session_lost_count >= 2:
                    break
            else:
                session_lost_count = 0

            width, height = os.get_terminal_size()
            if width != MONITOR_WIDTH:
                own_pane = os.environ.get("TMUX_PANE", "")
                if own_pane:
                    subprocess.run(
                        [
                            "tmux",
                            "resize-pane",
                            "-t",
                            own_pane,
                            "-x",
                            str(MONITOR_WIDTH),
                        ],
                        check=False,
                    )
                    width, height = os.get_terminal_size()
            output = monitor.render(width, height)
            sys.stdout.write("\033[H\033[2J" + output)
            sys.stdout.flush()
            state = load_state(files.state)
            prev_status = append_status_change(
                files.status_log, prev_status, state.get("phase", "")
            )
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
