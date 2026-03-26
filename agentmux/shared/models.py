from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SESSION_DIR_NAMES: dict[str, str] = {
    "product_management": "01_product_management",
    "planning": "02_planning",
    "research": "03_research",
    "design": "04_design",
    "implementation": "05_implementation",
    "review": "06_review",
    "docs": "07_docs",
    "completion": "08_completion",
}


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
class RuntimeFiles:
    project_dir: Path
    feature_dir: Path
    product_management_dir: Path
    planning_dir: Path
    research_dir: Path
    design_dir: Path
    implementation_dir: Path
    review_dir: Path
    docs_dir: Path
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
    state: Path
    runtime_state: Path
    orchestrator_log: Path
    created_files_log: Path

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.feature_dir).as_posix()
