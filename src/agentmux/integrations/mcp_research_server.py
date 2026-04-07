from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..shared.models import SESSION_DIR_NAMES
from ..workflow.handoff_artifacts import (
    submit_architecture as write_architecture_submission,
)
from ..workflow.handoff_artifacts import (
    submit_execution_plan as write_execution_plan_submission,
)
from ..workflow.handoff_artifacts import (
    submit_review as write_review_submission,
)
from ..workflow.handoff_artifacts import (
    submit_subplan as write_subplan_submission,
)

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


def _research_dir(
    topic: str, research_type: str, feature_dir: str | None = None
) -> Path:
    return (
        _feature_dir(feature_dir)
        / SESSION_DIR_NAMES["research"]
        / f"{research_type}-{topic}"
    )


def _request_content(
    context: str, questions: list[str], scope_hints: list[str] | None
) -> str:
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


@_tool()
def agentmux_submit_architecture(
    solution_overview: str,
    components: list[dict[str, Any]],
    interfaces_and_contracts: str,
    data_models: str,
    cross_cutting_concerns: str,
    technology_choices: str,
    risks_and_mitigations: str,
    feature_dir: str | None = None,
    design_handoff: str | None = None,
) -> str:
    """Submit architecture document.

    Validates input, writes architecture.yaml + architecture.md.
    """
    data: dict[str, Any] = {
        "solution_overview": solution_overview,
        "components": components,
        "interfaces_and_contracts": interfaces_and_contracts,
        "data_models": data_models,
        "cross_cutting_concerns": cross_cutting_concerns,
        "technology_choices": technology_choices,
        "risks_and_mitigations": risks_and_mitigations,
    }
    if design_handoff is not None:
        data["design_handoff"] = design_handoff

    return write_architecture_submission(_feature_dir(feature_dir), data)


@_tool()
def agentmux_submit_execution_plan(
    groups: list[dict[str, Any]],
    review_strategy: dict[str, Any],
    needs_design: bool,
    needs_docs: bool,
    doc_files: list[str],
    plan_overview: str,
    feature_dir: str | None = None,
) -> str:
    """Submit the execution plan. Validates and writes execution_plan.yaml + plan.md."""
    data: dict[str, Any] = {
        "groups": groups,
        "review_strategy": review_strategy,
        "needs_design": needs_design,
        "needs_docs": needs_docs,
        "doc_files": doc_files,
        "plan_overview": plan_overview,
    }

    return write_execution_plan_submission(_feature_dir(feature_dir), data)


@_tool()
def agentmux_submit_subplan(
    index: int,
    title: str,
    scope: str,
    owned_files: list[str],
    dependencies: str,
    implementation_approach: str,
    acceptance_criteria: str,
    tasks: list[str],
    feature_dir: str | None = None,
    isolation_rationale: str | None = None,
) -> str:
    """Submit a sub-plan.

    Validates and writes plan_N.yaml, plan_N.md, tasks_N.md.
    """
    data: dict[str, Any] = {
        "index": index,
        "title": title,
        "scope": scope,
        "owned_files": owned_files,
        "dependencies": dependencies,
        "implementation_approach": implementation_approach,
        "acceptance_criteria": acceptance_criteria,
        "tasks": tasks,
    }
    if isolation_rationale is not None:
        data["isolation_rationale"] = isolation_rationale

    return write_subplan_submission(_feature_dir(feature_dir), data)


@_tool()
def agentmux_submit_review(
    verdict: str,
    summary: str,
    feature_dir: str | None = None,
    findings: list[dict[str, Any]] | None = None,
    commit_message: str | None = None,
) -> str:
    """Submit a code review. Validates and writes review.yaml + review.md."""
    data: dict[str, Any] = {
        "verdict": verdict,
        "summary": summary,
    }
    if findings is not None:
        data["findings"] = findings
    if commit_message is not None:
        data["commit_message"] = commit_message

    return write_review_submission(_feature_dir(feature_dir), data)


if __name__ == "__main__":
    if mcp is None:
        raise SystemExit(
            "Missing dependency: mcp. "
            "Install with `python3 -m pip install -r requirements.txt`."
        )
    mcp.run()
