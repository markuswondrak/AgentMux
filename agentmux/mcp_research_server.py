from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .models import SESSION_DIR_NAMES

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - runtime dependency check
    FastMCP = None  # type: ignore[assignment]

TOPIC_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

mcp = FastMCP("agentmux-research") if FastMCP is not None else None


def _tool():
    if mcp is None:
        def decorate(func):
            return func

        return decorate
    return mcp.tool()


def _feature_dir(feature_dir: str | None = None) -> Path:
    raw = (feature_dir or os.environ.get("FEATURE_DIR", "")).strip()
    if not raw:
        raise RuntimeError("feature_dir is required.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise RuntimeError(f"feature_dir does not exist: {path}")
    return path


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


def _normalize_scope_hints(scope_hints: str | list[str] | None) -> list[str] | None:
    if scope_hints is None:
        return None
    if isinstance(scope_hints, str):
        cleaned = scope_hints.strip()
        return [cleaned] if cleaned else None
    cleaned = [hint.strip() for hint in scope_hints if hint and hint.strip()]
    return cleaned or None


def _research_dir(topic: str, research_type: str, feature_dir: str | None = None) -> Path:
    return _feature_dir(feature_dir) / SESSION_DIR_NAMES["research"] / f"{research_type}-{topic}"


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
        lines.extend(f"- {hint}" for hint in scope_hints)
    else:
        lines.append("- (none provided)")

    return "\n".join(lines).rstrip() + "\n"


def _dispatch(
    research_type: str,
    topic: str,
    context: str,
    questions: list[str],
    scope_hints: str | list[str] | None,
    feature_dir: str | None = None,
) -> str:
    normalized_topic = _validate_topic(topic)
    normalized_questions = _validate_questions(questions)
    normalized_scope_hints = _normalize_scope_hints(scope_hints)
    directory = _research_dir(normalized_topic, research_type, feature_dir)
    directory.mkdir(parents=True, exist_ok=True)

    request_path = directory / "request.md"
    request_path.write_text(
        _request_content(context, normalized_questions, normalized_scope_hints),
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


@_tool()
def agentmux_research_dispatch_code(
    topic: str,
    context: str,
    questions: list[str],
    feature_dir: str | None = None,
    scope_hints: str | list[str] | None = None,
) -> str:
    return _dispatch("code", topic, context, questions, scope_hints, feature_dir)


@_tool()
def agentmux_research_dispatch_web(
    topic: str,
    context: str,
    questions: list[str],
    feature_dir: str | None = None,
    scope_hints: str | list[str] | None = None,
) -> str:
    return _dispatch("web", topic, context, questions, scope_hints, feature_dir)


if __name__ == "__main__":
    if mcp is None:
        raise SystemExit("Missing dependency: mcp. Install with `python3 -m pip install -r requirements.txt`.")
    mcp.run()
