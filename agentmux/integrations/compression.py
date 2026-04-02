from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from ..shared.models import AgentConfig

# Providers supported by the headroom proxy and the env var each needs.
PROVIDER_BASE_URL_ENVS: dict[str, str] = {
    "claude": "ANTHROPIC_BASE_URL",
    "codex": "OPENAI_BASE_URL",
}

_PROXY_STATE_FILENAME = "headroom_proxy.json"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_compression_proxy(feature_dir: Path) -> int:
    """Start a headroom proxy subprocess and write its state to feature_dir.

    Returns the port the proxy is listening on.
    Raises SystemExit if headroom is not installed.
    """
    if shutil.which("headroom") is None:
        raise SystemExit(
            "headroom is not installed or not on PATH. "
            "Install it with: pip install 'headroom-ai[proxy]'"
        )

    port = find_free_port()
    proc = subprocess.Popen(
        ["headroom", "proxy", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _wait_for_proxy(port)

    state_file = feature_dir / _PROXY_STATE_FILENAME
    state_file.write_text(
        json.dumps({"port": port, "pid": proc.pid}),
        encoding="utf-8",
    )

    return port


def read_proxy_port(feature_dir: Path) -> int | None:
    """Return the proxy port recorded in feature_dir, or None if absent."""
    state_file = feature_dir / _PROXY_STATE_FILENAME
    if not state_file.exists():
        return None
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return int(data["port"])
    except (KeyError, ValueError, OSError):
        return None


def inject_compression_env(
    agents: dict[str, AgentConfig], port: int
) -> dict[str, AgentConfig]:
    """Return a new agents dict with proxy base-URL env vars injected
    for supported providers."""
    result: dict[str, AgentConfig] = {}
    for role, agent in agents.items():
        env_var = PROVIDER_BASE_URL_ENVS.get(agent.provider or "")
        if env_var:
            base_url = f"http://127.0.0.1:{port}"
            if env_var == "OPENAI_BASE_URL":
                base_url += "/v1"
            env = dict(agent.env or {})
            env[env_var] = base_url
            result[role] = replace(agent, env=env)
        else:
            result[role] = agent
    return result


def cleanup_compression(feature_dir: Path) -> None:
    """Terminate the headroom proxy process and remove the state file."""
    state_file = feature_dir / _PROXY_STATE_FILENAME
    if not state_file.exists():
        return

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        pid = int(data["pid"])
    except (KeyError, ValueError, OSError):
        state_file.unlink(missing_ok=True)
        return

    try:
        os.kill(pid, signal.SIGTERM)
        _wait_for_pid_exit(pid, timeout=5.0)
    except ProcessLookupError:
        pass
    finally:
        state_file.unlink(missing_ok=True)


def _wait_for_proxy(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise SystemExit(
        f"headroom proxy did not become ready on port {port} within {timeout:.0f}s."
    )


def _wait_for_pid_exit(pid: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    # Force kill if it didn't exit in time
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
