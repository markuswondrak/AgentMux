"""Helpers for validating and materializing structured handoff artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
    deps = data["dependencies"]
    if isinstance(deps, list):
        deps_text = "\n".join(f"- {d}" for d in deps)
    else:
        deps_text = str(deps).strip()
    lines.extend(["## Dependencies", "", deps_text, ""])
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


def generate_execution_plan_yaml(data: dict[str, Any]) -> dict[str, Any]:
    """Build an execution_plan.yaml dict from plan.yaml data.

    Converts groups[].plans[].index references to plan_N.md file references
    so that load_execution_plan() can consume it unchanged.
    """
    converted_groups = []
    for grp in data.get("groups", []):
        converted_plans = []
        for p in grp.get("plans", []):
            idx = p["index"]
            converted_plans.append({"file": f"plan_{idx}.md", "name": p["name"]})
        converted_groups.append(
            {
                "group_id": grp["group_id"],
                "mode": grp["mode"],
                "plans": converted_plans,
            }
        )
    return {
        "groups": converted_groups,
        "review_strategy": data.get("review_strategy", {}),
        "needs_design": data.get("needs_design", False),
        "needs_docs": data.get("needs_docs", False),
        "doc_files": data.get("doc_files", []),
    }


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
