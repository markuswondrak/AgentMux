"""Helpers for validating and materializing structured handoff artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..shared.models import SESSION_DIR_NAMES
from .handoff_contracts import validate_submission

_VALID_REVIEW_VERDICTS = {"pass", "fail"}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write data as YAML, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    path.write_text(content, encoding="utf-8")


def _write_md(path: Path, content: str) -> None:
    """Write markdown content, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _validate_or_raise(contract_name: str, data: dict[str, Any]) -> None:
    """Validate data against the named contract; raise on failure."""
    errors = validate_submission(contract_name, data)
    if errors:
        raise ValueError(
            f"Validation failed for '{contract_name}': " + "; ".join(errors)
        )


def generate_architecture_md(data: dict[str, Any]) -> str:
    """Generate human-readable markdown from architecture data."""
    lines = ["# Architecture", ""]
    lines.extend(["## Solution Overview", "", data["solution_overview"].strip(), ""])

    lines.append("## Components")
    lines.append("")
    for comp in data["components"]:
        lines.append(f"### {comp['name']}")
        lines.append("")
        lines.append(f"**Responsibility:** {comp['responsibility']}")
        interfaces = comp.get("interfaces")
        if interfaces:
            lines.append("")
            lines.append("**Interfaces:**")
            for iface in interfaces:
                lines.append(f"- {iface}")
        lines.append("")

    for section, key in [
        ("Interfaces and Contracts", "interfaces_and_contracts"),
        ("Data Models", "data_models"),
        ("Cross-Cutting Concerns", "cross_cutting_concerns"),
        ("Technology Choices", "technology_choices"),
        ("Risks and Mitigations", "risks_and_mitigations"),
    ]:
        lines.extend([f"## {section}", "", data[key].strip(), ""])

    if data.get("design_handoff"):
        lines.extend(["## Design Handoff", "", data["design_handoff"].strip(), ""])

    return "\n".join(lines)


def generate_plan_md(data: dict[str, Any]) -> str:
    """Generate plan.md from plan_overview content."""
    return data["plan_overview"].strip() + "\n"


def generate_subplan_md(data: dict[str, Any]) -> str:
    """Generate plan_N.md from subplan data."""
    lines = [f"# {data['title']}", ""]
    lines.extend(["## Scope", "", data["scope"].strip(), ""])
    lines.extend(["## Owned Files", ""])
    for file_path in data["owned_files"]:
        lines.append(f"- `{file_path}`")
    lines.append("")
    lines.extend(["## Dependencies", "", data["dependencies"].strip(), ""])
    lines.extend(
        ["## Implementation Approach", "", data["implementation_approach"].strip(), ""]
    )
    lines.extend(
        ["## Acceptance Criteria", "", data["acceptance_criteria"].strip(), ""]
    )
    if data.get("isolation_rationale"):
        lines.extend(
            ["## Isolation Rationale", "", data["isolation_rationale"].strip(), ""]
        )
    return "\n".join(lines)


def generate_tasks_md(data: dict[str, Any]) -> str:
    """Generate tasks_N.md checklist from subplan tasks."""
    lines = [f"# Tasks: {data['title']}", ""]
    for task in data["tasks"]:
        lines.append(f"- [ ] {task}")
    lines.append("")
    return "\n".join(lines)


def generate_review_md(data: dict[str, Any]) -> str:
    """Generate review.md with verdict on first line for runtime compatibility."""
    verdict = data["verdict"]
    lines = [f"verdict: {verdict}", ""]
    lines.extend(["## Summary", "", data["summary"].strip(), ""])

    if verdict == "fail" and data.get("findings"):
        lines.append("## Findings")
        lines.append("")
        for i, finding in enumerate(data["findings"], 1):
            lines.append(f"### Finding {i}")
            lines.append("")
            if finding.get("location"):
                lines.append(f"**Location:** `{finding['location']}`")
            lines.append(f"**Issue:** {finding['issue']}")
            if finding.get("severity"):
                lines.append(f"**Severity:** {finding['severity']}")
            lines.append(f"**Recommendation:** {finding['recommendation']}")
            lines.append("")

    if verdict == "pass" and data.get("commit_message"):
        lines.extend(
            ["## Suggested Commit Message", "", data["commit_message"].strip(), ""]
        )

    return "\n".join(lines)


def submit_architecture(feature_dir: Path, data: dict[str, Any]) -> str:
    """Validate and write architecture handoff artifacts."""
    _validate_or_raise("architecture", data)
    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    planning_dir.mkdir(parents=True, exist_ok=True)
    _write_yaml(planning_dir / "architecture.yaml", data)
    _write_md(planning_dir / "architecture.md", generate_architecture_md(data))
    return "Architecture submitted. Files: architecture.yaml, architecture.md"


def submit_execution_plan(feature_dir: Path, data: dict[str, Any]) -> str:
    """Validate and write execution plan artifacts."""
    _validate_or_raise("execution_plan", data)
    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    planning_dir.mkdir(parents=True, exist_ok=True)

    yaml_data = {
        "version": 1,
        "review_strategy": data["review_strategy"],
        "needs_design": data["needs_design"],
        "needs_docs": data["needs_docs"],
        "doc_files": data["doc_files"],
        "groups": data["groups"],
    }
    _write_yaml(planning_dir / "execution_plan.yaml", yaml_data)
    _write_md(planning_dir / "plan.md", generate_plan_md(data))
    return "Execution plan submitted. Files: execution_plan.yaml, plan.md"


def submit_subplan(feature_dir: Path, data: dict[str, Any]) -> str:
    """Validate and write subplan artifacts."""
    _validate_or_raise("subplan", data)
    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    planning_dir.mkdir(parents=True, exist_ok=True)

    index = data["index"]
    _write_yaml(planning_dir / f"plan_{index}.yaml", data)
    _write_md(planning_dir / f"plan_{index}.md", generate_subplan_md(data))
    _write_md(planning_dir / f"tasks_{index}.md", generate_tasks_md(data))
    return (
        f"Sub-plan {index} submitted. "
        f"Files: plan_{index}.yaml, plan_{index}.md, tasks_{index}.md"
    )


def submit_review(feature_dir: Path, data: dict[str, Any]) -> str:
    """Validate and write review artifacts."""
    _validate_or_raise("review", data)
    review_dir = feature_dir / SESSION_DIR_NAMES["review"]
    review_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml(review_dir / "review.yaml", data)
    _write_md(review_dir / "review.md", generate_review_md(data))
    return (
        f"Review submitted (verdict: {data['verdict']}). Files: review.yaml, review.md"
    )


def _load_review_yaml_data(review_dir: Path) -> dict[str, Any] | None:
    yaml_path = review_dir / "review.yaml"
    if not yaml_path.exists():
        return None
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict) or data.get("verdict") not in _VALID_REVIEW_VERDICTS:
        return None
    return None if validate_submission("review", data) else data


def review_yaml_has_verdict(review_dir: Path) -> bool:
    """Return True when review.yaml contains a valid review submission."""
    return _load_review_yaml_data(review_dir) is not None


def load_review_text(
    review_dir: Path, *, materialize_markdown: bool = False
) -> str | None:
    """Load the review text, falling back to canonical review.yaml when present."""
    markdown_path = review_dir / "review.md"
    yaml_data = _load_review_yaml_data(review_dir)
    if yaml_data is not None:
        rendered = generate_review_md(yaml_data)
        if materialize_markdown and not markdown_path.exists():
            _write_md(markdown_path, rendered)
        return rendered
    if not markdown_path.exists():
        return None
    try:
        return markdown_path.read_text(encoding="utf-8")
    except OSError:
        return None
