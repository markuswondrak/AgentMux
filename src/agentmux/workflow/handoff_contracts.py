"""Handoff contract definitions for structured agent submissions.

Defines the schema/interface for each MCP submission tool's parameters.
Used by:
- MCP submit tools for input validation
- Prompt rendering for fallback YAML examples (non-MCP providers)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Field specification
# ---------------------------------------------------------------------------

_VALID_VERDICTS = {"pass", "fail"}
_VALID_MODES = {"serial", "parallel"}
_VALID_SEVERITIES = {"low", "medium", "high"}


@dataclass(frozen=True)
class FieldSpec:
    """Specification for a single field in a handoff contract."""

    name: str
    type: str  # "str", "bool", "int", "list[str]", etc.
    required: bool = True
    description: str = ""
    allowed_values: frozenset[str] | None = None
    example: Any = None


@dataclass(frozen=True)
class HandoffContract:
    """Contract definition for a handoff submission."""

    name: str
    description: str
    fields: tuple[FieldSpec, ...]
    yaml_file: str  # relative path within feature dir (canonical artifact)
    md_file: str  # generated markdown companion (may equal yaml_file for md-only)

    def field_names(self) -> set[str]:
        return {f.name for f in self.fields}

    def required_fields(self) -> set[str]:
        return {f.name for f in self.fields if f.required}


# ---------------------------------------------------------------------------
# Contract: Architecture (MD-only — no structured YAML validation)
# ---------------------------------------------------------------------------

ARCHITECTURE_CONTRACT = HandoffContract(
    name="architecture",
    description="Technical architecture document produced by the architect.",
    yaml_file="02_architecting/architecture.md",
    md_file="02_architecting/architecture.md",
    fields=(),  # Free-form markdown; no structured field validation
)

# ---------------------------------------------------------------------------
# Contract: Plan (unified execution plan + all sub-plans in one file)
# ---------------------------------------------------------------------------

PLAN_CONTRACT = HandoffContract(
    name="plan",
    description=(
        "Unified execution plan with embedded sub-plans produced by the planner."
    ),
    yaml_file="04_planning/plan.yaml",
    md_file="04_planning/plan.md",
    fields=(
        FieldSpec(
            name="plan_overview",
            type="str",
            description="Human-readable plan summary (becomes plan.md content).",
        ),
        FieldSpec(
            name="review_strategy",
            type="dict",
            description=(
                "Review configuration: {severity: low|medium|high, focus: [...]}."
            ),
            example={"severity": "medium", "focus": ["security", "testing"]},
        ),
        FieldSpec(
            name="needs_design",
            type="bool",
            description="Whether a design phase is required.",
            example=False,
        ),
        FieldSpec(
            name="needs_docs",
            type="bool",
            description="Whether documentation updates are needed.",
            example=True,
        ),
        FieldSpec(
            name="doc_files",
            type="list[str]",
            description="Documentation files to create or update.",
            example=["docs/api.md"],
        ),
        FieldSpec(
            name="groups",
            type="list[dict]",
            description=(
                "Execution groups. Each: "
                "{group_id, mode: 'serial'|'parallel', plans: [{index, name}]}."
            ),
            example=[
                {
                    "group_id": "core",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "Core setup"}],
                }
            ],
        ),
        FieldSpec(
            name="subplans",
            type="list[dict]",
            description=(
                "Sub-plans for the coder. Each: "
                "{index, title, scope, owned_files, dependencies, "
                "implementation_approach, acceptance_criteria, tasks, "
                "isolation_rationale (optional)}."
            ),
            example=[
                {
                    "index": 1,
                    "title": "Core setup",
                    "scope": "Set up the foundation",
                    "owned_files": ["src/core.py"],
                    "dependencies": "None",
                    "implementation_approach": "Step by step",
                    "acceptance_criteria": "Tests pass",
                    "tasks": ["Create module", "Write tests"],
                }
            ],
        ),
    ),
)

# ---------------------------------------------------------------------------
# Contract: Review
# ---------------------------------------------------------------------------

REVIEW_CONTRACT = HandoffContract(
    name="review",
    description="Code review verdict and findings.",
    yaml_file="07_review/review.yaml",
    md_file="07_review/review.md",
    fields=(
        FieldSpec(
            name="verdict",
            type="str",
            description="Review outcome: 'pass' or 'fail'.",
            allowed_values=frozenset(_VALID_VERDICTS),
            example="pass",
        ),
        FieldSpec(
            name="summary",
            type="str",
            description="What was reviewed and the outcome.",
        ),
        FieldSpec(
            name="findings",
            type="list[dict]",
            required=False,
            description=(
                "On fail: list of issues. "
                "Each: {location, issue, severity, recommendation}."
            ),
            example=[
                {
                    "location": "src/auth.py:42",
                    "issue": "Missing input validation",
                    "severity": "high",
                    "recommendation": "Add email format check before database lookup.",
                }
            ],
        ),
        FieldSpec(
            name="commit_message",
            type="str",
            required=False,
            description="Suggested commit message (on pass).",
        ),
    ),
)

# ---------------------------------------------------------------------------
# Contract registry
# ---------------------------------------------------------------------------

CONTRACTS: dict[str, HandoffContract] = {
    c.name: c
    for c in (
        ARCHITECTURE_CONTRACT,
        PLAN_CONTRACT,
        REVIEW_CONTRACT,
    )
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationError(Exception):
    """Raised when a submission fails contract validation."""

    def __init__(self, contract_name: str, errors: list[str]) -> None:
        self.contract_name = contract_name
        self.errors = errors
        super().__init__(
            f"Handoff validation failed for '{contract_name}': {'; '.join(errors)}"
        )


def _check_type(value: Any, type_str: str) -> bool:  # noqa: PLR0911
    """Loose type check against a FieldSpec type string."""
    if type_str == "str":
        return isinstance(value, str) and bool(value.strip())
    if type_str in ("optional[str]",):
        return value is None or (isinstance(value, str) and bool(value.strip()))
    if type_str == "bool":
        return isinstance(value, bool)
    if type_str == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_str == "list[str]":
        return isinstance(value, list) and all(
            isinstance(v, str) and v.strip() for v in value
        )
    if type_str == "list[dict]":
        return isinstance(value, list) and all(isinstance(v, dict) for v in value)
    if type_str == "dict":
        return isinstance(value, dict)
    return True


def validate_submission(contract_name: str, data: dict[str, Any]) -> list[str]:
    """Validate *data* against the named contract.

    Returns a list of human-readable error strings (empty == valid).
    """
    contract = CONTRACTS.get(contract_name)
    if contract is None:
        return [f"Unknown contract: {contract_name}"]

    errors: list[str] = []

    # Required fields
    for fld in contract.fields:
        if fld.required and fld.name not in data:
            errors.append(f"Missing required field: {fld.name}")
            continue

        if fld.name not in data:
            continue

        value = data[fld.name]

        # Optional fields: treat empty string as "not provided" — skip type check
        if not fld.required and isinstance(value, str) and not value.strip():
            continue

        if not _check_type(value, fld.type):
            errors.append(
                f"Field '{fld.name}' has invalid type "
                f"(expected {fld.type}, got {type(value).__name__})."
            )
            continue

        if (
            fld.allowed_values
            and isinstance(value, str)
            and value not in fld.allowed_values
        ):
            errors.append(
                f"Field '{fld.name}' must be one of: "
                f"{', '.join(sorted(fld.allowed_values))} (got '{value}')."
            )

    # Contract-specific validation
    if contract_name == "plan":
        _validate_plan(data, errors)
    elif contract_name == "review":
        _validate_review(data, errors)

    return errors


def _validate_plan(data: dict[str, Any], errors: list[str]) -> None:
    version = data.get("version")
    if version != 2:
        errors.append(f"plan.yaml must have version: 2 (got {version!r}).")
        return  # skip further checks; structure may be completely different
    groups = data.get("groups")
    if isinstance(groups, list) and len(groups) == 0:
        errors.append("groups must contain at least one group.")
    subplans = data.get("subplans")
    subplan_indices: set[int] = set()
    if isinstance(subplans, list):
        if len(subplans) == 0:
            errors.append("subplans must contain at least one sub-plan.")
        for i, sp in enumerate(subplans, 1):
            if not isinstance(sp, dict):
                errors.append(f"subplans[{i}] must be a mapping.")
                continue
            idx = sp.get("index")
            if not isinstance(idx, int) or isinstance(idx, bool) or idx < 1:
                errors.append(f"subplans[{i}].index must be an integer >= 1.")
            else:
                if idx in subplan_indices:
                    errors.append(f"subplans[{i}] has duplicate index {idx}.")
                subplan_indices.add(idx)
            for required_str in (
                "title",
                "scope",
                "dependencies",
                "implementation_approach",
                "acceptance_criteria",
            ):
                val = sp.get(required_str)
                if not val or not str(val).strip():
                    errors.append(f"subplans[{i}].{required_str} must not be empty.")
            tasks = sp.get("tasks")
            if not isinstance(tasks, list) or len(tasks) == 0:
                errors.append(f"subplans[{i}].tasks must be a non-empty list.")
            owned = sp.get("owned_files")
            if not isinstance(owned, list) or len(owned) == 0:
                errors.append(f"subplans[{i}].owned_files must be a non-empty list.")

    if isinstance(groups, list):
        seen_ids: set[str] = set()
        seen_refs: set[int] = set()
        for i, grp in enumerate(groups, 1):
            if not isinstance(grp, dict):
                errors.append(f"groups[{i}] must be a mapping.")
                continue
            gid = grp.get("group_id", "")
            if not gid:
                errors.append(f"groups[{i}] missing 'group_id'.")
            elif gid in seen_ids:
                errors.append(f"groups[{i}] has duplicate group_id '{gid}'.")
            else:
                seen_ids.add(gid)
            mode = grp.get("mode", "")
            if mode not in _VALID_MODES:
                errors.append(
                    f"groups[{i}].mode must be 'serial' or 'parallel' (got '{mode}')."
                )
            plans = grp.get("plans")
            if not isinstance(plans, list) or not plans:
                errors.append(f"groups[{i}].plans must be a non-empty list.")
            elif isinstance(plans, list):
                for j, p in enumerate(plans, 1):
                    if not isinstance(p, dict):
                        errors.append(f"groups[{i}].plans[{j}] must be a mapping.")
                        continue
                    pidx = p.get("index")
                    if not isinstance(pidx, int) or isinstance(pidx, bool) or pidx < 1:
                        errors.append(
                            f"groups[{i}].plans[{j}] must have a valid 'index'."
                        )
                    elif pidx in seen_refs:
                        errors.append(
                            f"groups[{i}].plans[{j}] duplicates plan index {pidx}."
                        )
                    else:
                        seen_refs.add(pidx)
                        if subplan_indices and pidx not in subplan_indices:
                            errors.append(
                                f"groups[{i}].plans[{j}] references index {pidx} "
                                "which has no matching subplan."
                            )
                    if not p.get("name"):
                        errors.append(f"groups[{i}].plans[{j}] must have 'name'.")

    # Ensure every subplan is referenced by exactly one group entry.
    if subplan_indices and isinstance(groups, list):
        unreferenced = subplan_indices - seen_refs
        for idx in sorted(unreferenced):
            errors.append(f"subplan with index {idx} is not referenced by any group.")

    # Enforce contiguous 1..N indexes (required by implementation scheduler).
    if seen_refs:
        max_idx = max(seen_refs)
        missing = sorted(set(range(1, max_idx + 1)) - seen_refs)
        if missing:
            missing_csv = ", ".join(str(i) for i in missing)
            errors.append(
                f"plan indices must be contiguous from 1..{max_idx};"
                f" missing: {missing_csv}."
            )

    strategy = data.get("review_strategy")
    if isinstance(strategy, dict):
        sev = strategy.get("severity")
        if not sev:
            errors.append("review_strategy.severity is required.")
        elif sev not in _VALID_SEVERITIES:
            errors.append(
                f"review_strategy.severity must be one of: "
                f"{', '.join(sorted(_VALID_SEVERITIES))} (got '{sev}')."
            )


def _validate_review(data: dict[str, Any], errors: list[str]) -> None:
    verdict = data.get("verdict")
    findings = data.get("findings")

    if verdict == "fail":
        if not findings or not isinstance(findings, list) or len(findings) == 0:
            errors.append("A 'fail' verdict requires non-empty 'findings'.")
        elif isinstance(findings, list):
            for i, finding in enumerate(findings, 1):
                if not isinstance(finding, dict):
                    errors.append(f"findings[{i}] must be a mapping.")
                    continue
                if not finding.get("issue"):
                    errors.append(f"findings[{i}] missing 'issue'.")
                if not finding.get("recommendation"):
                    errors.append(f"findings[{i}] missing 'recommendation'.")


# ---------------------------------------------------------------------------
# Prompt rendering helper
# ---------------------------------------------------------------------------


def render_contract_prompt(contract_name: str) -> str:
    """Render a compact YAML example for embedding in agent prompts.

    Used as fallback documentation when agents cannot use MCP tools.
    """
    contract = CONTRACTS.get(contract_name)
    if contract is None:
        return f"<!-- unknown contract: {contract_name} -->"

    lines = [
        f"### {contract.description}",
        "",
        f"Write `{contract.yaml_file}` with this structure:",
        "",
        "```yaml",
    ]
    for fld in contract.fields:
        optional = "" if fld.required else "  # optional"
        if fld.example is not None:
            lines.append(f"{fld.name}: {_yaml_inline(fld.example)}{optional}")
        else:
            lines.append(f"{fld.name}: ...{optional}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def _yaml_inline(value: Any) -> str:
    """Produce a compact inline YAML representation for examples."""
    rendered = yaml.safe_dump(
        value,
        default_flow_style=True,
        sort_keys=False,
        width=10_000,
    ).strip()
    if rendered.endswith("\n..."):
        rendered = rendered[: -len("\n...")].rstrip()
    return rendered
