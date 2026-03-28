from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SESSION_DIR_NAMES: dict[str, str] = {
    "product_management": "01_product_management",
    "planning": "02_planning",
    "research": "03_research",
    "design": "04_design",
    "implementation": "05_implementation",
    "review": "06_review",
    "completion": "08_completion",
}

PROMPT_AGENT_ROLES: tuple[str, ...] = (
    "architect",
    "code-researcher",
    "coder",
    "designer",
    "product-manager",
    "reviewer",
    "web-researcher",
)

PREFERENCE_PROPOSAL_SOURCES: tuple[str, ...] = (
    "product-manager",
    "architect",
    "reviewer",
)


@dataclass(frozen=True)
class AgentConfig:
    role: str
    cli: str
    model: str
    model_flag: str = "--model"
    args: list[str] = None
    env: dict[str, str] | None = None
    trust_snippet: str | None = None
    provider: str | None = None


@dataclass(frozen=True)
class GitHubConfig:
    base_branch: str = "main"
    draft: bool = True
    branch_prefix: str = "feature/"


@dataclass(frozen=True)
class CompletionSettings:
    skip_final_approval: bool = False

    @property
    def require_final_approval(self) -> bool:
        return not self.skip_final_approval


@dataclass(frozen=True)
class WorkflowSettings:
    completion: CompletionSettings = field(default_factory=CompletionSettings)


@dataclass(frozen=True)
class RuntimeFiles:
    project_dir: Path
    feature_dir: Path
    product_management_dir: Path
    planning_dir: Path
    research_dir: Path
    design_dir: Path
    implementation_dir: Path
    review_dir: Path
    completion_dir: Path
    context: Path
    requirements: Path
    plan: Path
    tasks: Path
    execution_plan: Path
    design: Path
    review: Path
    fix_request: Path
    changes: Path
    pm_preference_proposal: Path
    architect_preference_proposal: Path
    reviewer_preference_proposal: Path
    state: Path
    runtime_state: Path
    orchestrator_log: Path
    created_files_log: Path

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.feature_dir).as_posix()


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"`{key}` must be a string.")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"`{key}` must not be empty.")
    return stripped


@dataclass(frozen=True)
class PreferenceProposalEntry:
    target_role: str
    bullet: str

    @classmethod
    def from_dict(cls, payload: Any) -> PreferenceProposalEntry:
        if not isinstance(payload, dict):
            raise ValueError("Approved preference entries must be JSON objects.")
        target_role = _require_string(payload, "target_role")
        if target_role not in set(PROMPT_AGENT_ROLES):
            raise ValueError(
                "Approved preference entries must target one of "
                f"{', '.join(PROMPT_AGENT_ROLES)}."
            )
        bullet = _require_string(payload, "bullet")
        return cls(target_role=target_role, bullet=bullet)

    def to_dict(self) -> dict[str, str]:
        return {
            "target_role": self.target_role,
            "bullet": self.bullet,
        }


@dataclass(frozen=True)
class PreferenceProposal:
    source_role: str
    approved: tuple[PreferenceProposalEntry, ...]

    @classmethod
    def from_dict(cls, payload: Any) -> PreferenceProposal:
        if not isinstance(payload, dict):
            raise ValueError("Preference proposal payload must be a JSON object.")
        source_role = _require_string(payload, "source_role")
        if source_role not in set(PREFERENCE_PROPOSAL_SOURCES):
            raise ValueError(
                "Preference proposal source must be one of "
                f"{', '.join(PREFERENCE_PROPOSAL_SOURCES)}."
            )
        approved_raw = payload.get("approved")
        if not isinstance(approved_raw, list):
            raise ValueError("Preference proposal `approved` must be a list.")
        approved = tuple(PreferenceProposalEntry.from_dict(item) for item in approved_raw)
        return cls(
            source_role=source_role,
            approved=approved,
        )

    @classmethod
    def from_json(cls, raw_json: str) -> PreferenceProposal:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Preference proposal file must contain valid JSON.") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_role": self.source_role,
            "approved": [entry.to_dict() for entry in self.approved],
        }
