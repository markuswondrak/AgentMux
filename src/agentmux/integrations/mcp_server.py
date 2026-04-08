from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..runtime.tool_events import append_tool_event
from ..shared.models import SESSION_DIR_NAMES

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
    path = (Path.cwd() / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.exists():
        raise RuntimeError(f"feature_dir does not exist: {path}")
    return path


def _log_path(feature_dir: str | None = None) -> Path:
    return _feature_dir(feature_dir) / "tool_events.jsonl"


def _validate_topic(topic: str) -> str:
    normalized = topic.strip()
    if not normalized or not TOPIC_PATTERN.fullmatch(normalized):
        raise ValueError(
            "topic must be a non-empty slug (lowercase alphanumeric and hyphens)."
        )
    return normalized


def _validate_questions(questions: list[str]) -> list[str]:
    cleaned = [
        question.strip() for question in questions if question and question.strip()
    ]
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


def _validate_or_raise(contract_name: str, data: dict[str, Any]) -> None:
    """Validate data against the contract for the given name.

    Raises ValueError with details if validation fails.
    """
    from ..workflow.handoff_contracts import ValidationError, validate_submission

    try:
        errors = validate_submission(contract_name, data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    if errors:
        raise ValueError("; ".join(errors))


# ---------------------------------------------------------------------------
# Research dispatch tools
# ---------------------------------------------------------------------------


@_tool()
def research_dispatch_code(
    topic: str,
    context: str,
    questions: list[str],
    feature_dir: str | None = None,
    scope_hints: str | list[str] | None = None,
) -> str:
    """Dispatch a code-research task."""
    normalized_topic = _validate_topic(topic)
    normalized_questions = _validate_questions(questions)
    normalized_scope_hints = _normalize_scope_hints(scope_hints)
    payload = {
        "topic": normalized_topic,
        "context": context.strip(),
        "questions": normalized_questions,
        "scope_hints": normalized_scope_hints,
        "research_type": "code",
    }
    append_tool_event(_log_path(feature_dir), "research_dispatch_code", payload)
    return f"Code research on '{normalized_topic}' dispatched."


@_tool()
def research_dispatch_web(
    topic: str,
    context: str,
    questions: list[str],
    feature_dir: str | None = None,
    scope_hints: str | list[str] | None = None,
) -> str:
    """Dispatch a web-research task."""
    normalized_topic = _validate_topic(topic)
    normalized_questions = _validate_questions(questions)
    normalized_scope_hints = _normalize_scope_hints(scope_hints)
    payload = {
        "topic": normalized_topic,
        "context": context.strip(),
        "questions": normalized_questions,
        "scope_hints": normalized_scope_hints,
        "research_type": "web",
    }
    append_tool_event(_log_path(feature_dir), "research_dispatch_web", payload)
    return f"Web research on '{normalized_topic}' dispatched."


# ---------------------------------------------------------------------------
# Submission tools
# ---------------------------------------------------------------------------


def _read_yaml_for_signal(yaml_path: Path, contract_name: str) -> dict[str, Any]:
    """Read and validate a YAML file written by the agent.

    Raises ValueError if the file is missing, unparseable, or invalid.
    """
    if not yaml_path.exists():
        raise ValueError(
            f"{yaml_path.name} not found at {yaml_path}. "
            "Write the file before calling this tool."
        )
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse {yaml_path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path.name} must be a YAML mapping.")
    _validate_or_raise(contract_name, data)
    return data


@_tool()
def submit_architecture(
    feature_dir: str | None = None,
) -> str:
    """Signal architecture completion.

    Checks that the agent-written 02_planning/architecture.md exists and has
    content, then appends a completion signal to tool_events.jsonl.
    Write the Markdown file before calling this tool.
    """
    feature = _feature_dir(feature_dir)
    md_path = feature / SESSION_DIR_NAMES["planning"] / "architecture.md"
    if not md_path.exists():
        raise ValueError(
            "architecture.md not found. Write the file before calling this tool."
        )
    if not md_path.read_text(encoding="utf-8").strip():
        raise ValueError("architecture.md is empty.")
    append_tool_event(_log_path(feature_dir), "submit_architecture", {})
    return "Architecture submitted."


@_tool()
def submit_plan(
    feature_dir: str | None = None,
) -> str:
    """Signal execution plan completion.

    Reads and validates the agent-written 02_planning/plan.yaml (version: 2),
    then appends a completion signal to tool_events.jsonl.
    Write plan.yaml before calling this tool.
    """
    feature = _feature_dir(feature_dir)
    yaml_path = feature / SESSION_DIR_NAMES["planning"] / "plan.yaml"
    _read_yaml_for_signal(yaml_path, "plan")
    append_tool_event(_log_path(feature_dir), "submit_plan", {})
    return "Plan submitted."


@_tool()
def submit_review(
    feature_dir: str | None = None,
) -> str:
    """Signal review completion.

    Reads and validates the agent-written 06_review/review.yaml,
    then appends a completion signal to tool_events.jsonl.
    Write the YAML file before calling this tool.
    """
    feature = _feature_dir(feature_dir)
    yaml_path = feature / SESSION_DIR_NAMES["review"] / "review.yaml"
    data = _read_yaml_for_signal(yaml_path, "review")
    verdict = data.get("verdict", "unknown")
    append_tool_event(_log_path(feature_dir), "submit_review", {})
    return f"Review submitted (verdict: {verdict})."


# ---------------------------------------------------------------------------
# Completion-signal tools
# ---------------------------------------------------------------------------


@_tool()
def submit_done(
    subplan_index: int,
    feature_dir: str | None = None,
) -> str:
    """Mark a sub-plan as done."""
    if not isinstance(subplan_index, int) or subplan_index < 1:
        raise ValueError("subplan_index must be an integer >= 1.")
    append_tool_event(
        _log_path(feature_dir), "submit_done", {"subplan_index": subplan_index}
    )
    return f"Sub-plan {subplan_index} marked done."


@_tool()
def submit_research_done(
    topic: str,
    type: str,
    feature_dir: str | None = None,
) -> str:
    """Mark a research task as done."""
    normalized = _validate_topic(topic)
    if type not in ("code", "web"):
        raise ValueError("type must be 'code' or 'web'.")
    append_tool_event(
        _log_path(feature_dir),
        "submit_research_done",
        {"topic": normalized, "type": type, "role_type": type},
    )
    return f"Research on '{normalized}' ({type}) marked done."


@_tool()
def submit_pm_done(
    feature_dir: str | None = None,
) -> str:
    """Mark the product management phase as done."""
    append_tool_event(_log_path(feature_dir), "submit_pm_done", {})
    return "Product management phase done."


if __name__ == "__main__":
    if mcp is None:
        raise SystemExit(
            "Missing dependency: mcp. "
            "Install with `python3 -m pip install -r requirements.txt`."
        )
    mcp.run()
