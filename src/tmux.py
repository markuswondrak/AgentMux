from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path

from .models import AgentConfig

TRUST_PROMPT_SNIPPET = "Do you trust the contents of this directory?"


def run_command(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=True,
    )


def build_agent_command(agent: AgentConfig) -> str:
    extra_args = " ".join(shlex.quote(a) for a in (agent.args or []))
    return f"{shlex.quote(agent.cli)} --model {shlex.quote(agent.model)}" + (
        f" {extra_args}" if extra_args else ""
    )


def tmux_session_exists(session_name: str) -> bool:
    result = run_command(["tmux", "has-session", "-t", session_name], check=False)
    return result.returncode == 0


def tmux_new_session(session_name: str, architect: AgentConfig) -> dict[str, str | None]:
    architect_cmd = build_agent_command(architect)
    result = run_command([
        "tmux", "new-session", "-d", "-s", session_name,
        "-n", architect.role, "-P", "-F", "#{pane_id}", architect_cmd,
    ])
    architect_pane = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", architect_pane, "-T", architect.role])
    return {"architect": architect_pane, "coder": None}


def create_agent_pane(session_name: str, agent_name: str, agents: dict[str, AgentConfig]) -> str:
    agent = agents[agent_name]
    agent_cmd = build_agent_command(agent)
    result = run_command([
        "tmux", "split-window", "-h", "-t", session_name,
        "-P", "-F", "#{pane_id}", agent_cmd,
    ])
    pane_id = result.stdout.strip()
    run_command(["tmux", "select-pane", "-t", pane_id, "-T", agent.role])
    pane_count_result = run_command(["tmux", "list-panes", "-t", session_name, "-F", "#{pane_id}"])
    pane_count = len([line for line in pane_count_result.stdout.splitlines() if line.strip()])
    layout = "tiled" if pane_count >= 3 else "even-horizontal"
    run_command(["tmux", "select-layout", "-t", session_name, layout])
    accept_trust_prompt(pane_id)
    return pane_id


def kill_agent_pane(pane_id: str | None) -> None:
    if not pane_id:
        return
    run_command(["tmux", "kill-pane", "-t", pane_id], check=False)


def tmux_kill_session(session_name: str) -> None:
    run_command(["tmux", "kill-session", "-t", session_name], check=False)


def capture_pane(target_pane: str, history_lines: int = 160) -> str:
    result = run_command(["tmux", "capture-pane", "-p", "-S", f"-{history_lines}", "-t", target_pane])
    return result.stdout


def tmux_pane_exists(target_pane: str | None) -> bool:
    if not target_pane:
        return False
    result = run_command(
        ["tmux", "display-message", "-p", "-t", target_pane, "#{pane_id}"],
        check=False,
    )
    return result.returncode == 0


def send_text(target_pane: str, text: str) -> None:
    # select-window first so the attached client visually switches to the right pane
    if ":" in target_pane:
        session_window = target_pane.rsplit(".", 1)[0]
        run_command(["tmux", "select-window", "-t", session_window])
    run_command(["tmux", "select-pane", "-t", target_pane])
    run_command(["tmux", "send-keys", "-t", target_pane, "-l", text])
    time.sleep(3.0)
    run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])
    time.sleep(0.5)
    run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])


def normalize_prompt(content: str) -> str:
    # Interactive CLIs commonly keep pasted multi-line content as a draft.
    # Sending a single line makes Enter behave like a real submit.
    return re.sub(r"\s+", " ", content).strip()


def send_prompt(target_pane: str, prompt_file: Path) -> None:
    if not tmux_pane_exists(target_pane):
        return
    prompt = normalize_prompt(prompt_file.read_text(encoding="utf-8"))
    send_text(target_pane, prompt)


def accept_trust_prompt(target_pane: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if TRUST_PROMPT_SNIPPET in capture_pane(target_pane):
            run_command(["tmux", "select-pane", "-t", target_pane])
            run_command(["tmux", "send-keys", "-t", target_pane, "Enter"])
            return
        time.sleep(0.2)
