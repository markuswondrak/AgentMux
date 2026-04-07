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
_VALID_FOCUS_AREAS = {
    "security",
    "performance",
    "testing",
    "error-handling",
    "accessibility",
    "documentation",
    "maintainability",
}
_VALID_FINDING_SEVERITIES = {"critical", "high", "medium", "low", "info"}


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
    yaml_file: str  # relative path within feature dir
    md_file: str  # generated markdown companion

    def field_names(self) -> set[str]:
        return {f.name for f in self.fields}

    def required_fields(self) -> set[str]:
        return {f.name for f in self.fields if f.required}


# ---------------------------------------------------------------------------
# Contract: Architecture
# ---------------------------------------------------------------------------

ARCHITECTURE_CONTRACT = HandoffContract(
    name="architecture",
    description="Technical architecture document produced by the architect.",
    yaml_file="02_planning/architecture.yaml",
    md_file="02_planning/architecture.md",
    fields=(
        FieldSpec(
            name="solution_overview",
            type="str",
            description="High-level approach and rationale.",
            example="Use a plugin-based architecture with dynamic loading.",
        ),
        FieldSpec(
            name="components",
            type="list[dict]",
            description=(
                "System components. Each: {name, responsibility, interfaces: [...]}."
            ),
            example=[
                {
                    "name": "AuthService",
                    "responsibility": "Handles user authentication",
                    "interfaces": ["login()", "logout()", "verify_token()"],
                }
            ],
        ),
        FieldSpec(
            name="interfaces_and_contracts",
            type="str",
            description="API boundaries, data formats, protocols.",
        ),
        FieldSpec(
            name="data_models",
            type="str",
            description="Key entities, relationships, storage.",
        ),
        FieldSpec(
            name="cross_cutting_concerns",
            type="str",
            description="Error handling, logging, security, testing strategy.",
        ),
        FieldSpec(
            name="technology_choices",
            type="str",
            description="Tools, libraries, frameworks with rationale.",
        ),
        FieldSpec(
            name="risks_and_mitigations",
            type="str",
            description="Known risks and mitigation strategies.",
        ),
        FieldSpec(
            name="design_handoff",
            type="str",
            required=False,
            description="Optional notes for the designer if UI work is needed.",
        ),
    ),
)

# ---------------------------------------------------------------------------
# Contract: Execution Plan (merged plan_meta + execution_plan)
# ---------------------------------------------------------------------------

EXECUTION_PLAN_CONTRACT = HandoffContract(
    name="execution_plan",
    description="Merged execution plan with scheduling groups and metadata.",
    yaml_file="02_planning/execution_plan.yaml",
    md_file="02_planning/plan.md",
    fields=(
        FieldSpec(
            name="groups",
            type="list[dict]",
            description=(
                "Execution groups. Each: "
                "{group_id, mode: 'serial'|'parallel', plans: [{file, name}]}."
            ),
            example=[
                {
                    "group_id": "core",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Core setup"}],
                }
            ],
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
            name="plan_overview",
            type="str",
            description="Human-readable plan summary (becomes plan.md content).",
        ),
    ),
)

# ---------------------------------------------------------------------------
# Contract: Subplan
# ---------------------------------------------------------------------------

SUBPLAN_CONTRACT = HandoffContract(
    name="subplan",
    description="Individual execution sub-plan for the coder.",
    yaml_file="02_planning/plan_{index}.yaml",
    md_file="02_planning/plan_{index}.md",
    fields=(
        FieldSpec(
            name="index",
            type="int",
            description="Sub-plan number (1, 2, 3, ...).",
            example=1,
        ),
        FieldSpec(
            name="title",
            type="str",
            description="Short descriptive title.",
            example="Implement user authentication module",
        ),
        FieldSpec(
            name="scope",
            type="str",
            description="What this sub-plan covers.",
        ),
        FieldSpec(
            name="owned_files",
            type="list[str]",
            description="Files created or modified (for parallel isolation).",
            example=["src/auth.py", "tests/test_auth.py"],
        ),
        FieldSpec(
            name="dependencies",
            type="str",
            description="What this sub-plan depends on.",
        ),
        FieldSpec(
            name="implementation_approach",
            type="str",
            description="How to implement — step-by-step approach.",
        ),
        FieldSpec(
            name="acceptance_criteria",
            type="str",
            description="Testable criteria for completion.",
        ),
        FieldSpec(
            name="tasks",
            type="list[str]",
            description="Task checklist items for progress tracking.",
            example=["Create auth module", "Add login endpoint", "Write tests"],
        ),
        FieldSpec(
            name="isolation_rationale",
            type="str",
            required=False,
            description="Why this sub-plan is safe for parallel execution.",
        ),
    ),
)

# ---------------------------------------------------------------------------
# Contract: Review
# ---------------------------------------------------------------------------

REVIEW_CONTRACT = HandoffContract(
    name="review",
    description="Code review verdict and findings.",
    yaml_file="06_review/review.yaml",
    md_file="06_review/review.md",
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
        EXECUTION_PLAN_CONTRACT,
        SUBPLAN_CONTRACT,
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
    if contract_name == "architecture":
        _validate_architecture(data, errors)
    elif contract_name == "execution_plan":
        _validate_execution_plan(data, errors)
    elif contract_name == "subplan":
        _validate_subplan(data, errors)
    elif contract_name == "review":
        _validate_review(data, errors)

    return errors


def _validate_architecture(data: dict[str, Any], errors: list[str]) -> None:
    components = data.get("components")
    if isinstance(components, list):
        for i, comp in enumerate(components, 1):
            if not isinstance(comp, dict):
                continue
            if not comp.get("name"):
                errors.append(f"components[{i}] missing 'name'.")
            if not comp.get("responsibility"):
                errors.append(f"components[{i}] missing 'responsibility'.")


def _validate_execution_plan(data: dict[str, Any], errors: list[str]) -> None:
    groups = data.get("groups")
    if isinstance(groups, list) and len(groups) == 0:
        errors.append("groups must contain at least one group.")
    if isinstance(groups, list):
        seen_ids: set[str] = set()
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
                    elif not p.get("file") or not p.get("name"):
                        errors.append(
                            f"groups[{i}].plans[{j}] must have 'file' and 'name'."
                        )

    strategy = data.get("review_strategy")
    if isinstance(strategy, dict):
        sev = strategy.get("severity", "")
        if sev and sev not in _VALID_SEVERITIES:
            errors.append(
                f"review_strategy.severity must be one of: "
                f"{', '.join(sorted(_VALID_SEVERITIES))} (got '{sev}')."
            )


def _validate_subplan(data: dict[str, Any], errors: list[str]) -> None:
    idx = data.get("index")
    if isinstance(idx, int) and idx < 1:
        errors.append("index must be >= 1.")

    tasks = data.get("tasks")
    if isinstance(tasks, list) and len(tasks) == 0:
        errors.append("tasks must contain at least one item.")

    owned = data.get("owned_files")
    if isinstance(owned, list) and len(owned) == 0:
        errors.append("owned_files must contain at least one item.")


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
