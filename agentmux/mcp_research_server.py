from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - runtime dependency check
    FastMCP = None  # type: ignore[assignment]

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - runtime dependency check
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None

TOPIC_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VALID_RESEARCH_TYPES = {"code", "web"}

mcp = FastMCP("agentmux-research") if FastMCP is not None else None


def _tool():
    if mcp is None:
        def decorate(func):
            return func

        return decorate
    return mcp.tool()


def _feature_dir() -> Path:
    raw = os.environ.get("FEATURE_DIR", "").strip()
    if not raw:
        raise RuntimeError("FEATURE_DIR environment variable is required.")
    return Path(raw)


def _validate_topic(topic: str) -> str:
    normalized = topic.strip()
    if not normalized or not TOPIC_PATTERN.fullmatch(normalized):
        raise ValueError("topic must be a non-empty slug (lowercase alphanumeric and hyphens).")
    return normalized


def _validate_questions(questions: list[str]) -> list[str]:
    cleaned = [question.strip() for question in questions if question and question.strip()]
    if not cleaned:
        raise ValueError("questions must contain at least one non-empty question.")
    return cleaned


def _research_dir(topic: str, research_type: str) -> Path:
    return _feature_dir() / "research" / f"{research_type}-{topic}"


def _request_content(context: str, questions: list[str], scope_hints: list[str] | None) -> str:
    lines = [
        "## Context",
        context.strip(),
        "",
        "## Questions",
    ]
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question}")

    lines.extend(["", "## Scope hints"])
    if scope_hints:
        hints = [hint.strip() for hint in scope_hints if hint and hint.strip()]
        if hints:
            lines.extend(f"- {hint}" for hint in hints)
        else:
            lines.append("- (none provided)")
    else:
        lines.append("- (none provided)")

    return "\n".join(lines).rstrip() + "\n"


def _dispatch(research_type: str, topic: str, context: str, questions: list[str], scope_hints: list[str] | None) -> str:
    normalized_topic = _validate_topic(topic)
    normalized_questions = _validate_questions(questions)
    directory = _research_dir(normalized_topic, research_type)
    directory.mkdir(parents=True, exist_ok=True)

    request_path = directory / "request.md"
    request_path.write_text(
        _request_content(context, normalized_questions, scope_hints),
        encoding="utf-8",
    )

    label = "Code research" if research_type == "code" else "Web research"
    return f"{label} on '{normalized_topic}' dispatched."


def _result_content(topic: str, directory: Path, detail: bool) -> str:
    filename = "detail.md" if detail else "summary.md"
    target = directory / filename
    if not target.exists():
        return f"Research on '{topic}' completed but {filename} is missing."
    return target.read_text(encoding="utf-8")


class _DoneHandler(FileSystemEventHandler):
    def __init__(self, done_marker: Path, done_event: threading.Event) -> None:
        super().__init__()
        self._done_marker = done_marker
        self._done_event = done_event

    def on_any_event(self, event: FileSystemEvent) -> None:
        _ = event
        if self._done_marker.exists():
            self._done_event.set()


def _await_done(done_marker: Path, directory: Path, timeout: int) -> bool:
    if done_marker.exists():
        return True

    safe_timeout = max(timeout, 0)
    if Observer is None:
        deadline = time.monotonic() + safe_timeout
        while time.monotonic() <= deadline:
            if done_marker.exists():
                return True
            time.sleep(0.1)
        return False

    done_event = threading.Event()
    observer = Observer()
    observer.schedule(_DoneHandler(done_marker, done_event), str(directory), recursive=False)
    observer.start()

    try:
        # Guard against race if marker appeared after pre-check but before observer start.
        if done_marker.exists():
            done_event.set()
        done_event.wait(timeout=safe_timeout)
        return done_event.is_set() or done_marker.exists()
    finally:
        observer.stop()
        observer.join()


@_tool()
def agentmux_research_dispatch_code(
    topic: str,
    context: str,
    questions: list[str],
    scope_hints: list[str] | None = None,
) -> str:
    return _dispatch("code", topic, context, questions, scope_hints)


@_tool()
def agentmux_research_dispatch_web(
    topic: str,
    context: str,
    questions: list[str],
    scope_hints: list[str] | None = None,
) -> str:
    return _dispatch("web", topic, context, questions, scope_hints)


@_tool()
def agentmux_research_await(
    topic: str,
    research_type: str,
    detail: bool = False,
    timeout: int = 300,
) -> str:
    normalized_topic = _validate_topic(topic)
    if research_type not in VALID_RESEARCH_TYPES:
        raise ValueError("research_type must be 'code' or 'web'.")

    directory = _research_dir(normalized_topic, research_type)
    if not directory.exists():
        return "No research task found. Did you dispatch it first?"

    done_marker = directory / "done"
    if done_marker.exists():
        return _result_content(normalized_topic, directory, detail)

    if not _await_done(done_marker, directory, timeout):
        return f"Research on '{normalized_topic}' timed out after {timeout}s."

    return _result_content(normalized_topic, directory, detail)


if __name__ == "__main__":
    if mcp is None:
        raise SystemExit("Missing dependency: mcp. Install with `python3 -m pip install -r requirements.txt`.")
    mcp.run()
