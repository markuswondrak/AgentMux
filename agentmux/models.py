from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    role: str
    cli: str
    model: str
    model_flag: str = "--model"
    args: list[str] = None
    trust_snippet: str | None = None


@dataclass(frozen=True)
class GitHubConfig:
    base_branch: str = "main"
    draft: bool = True
    branch_prefix: str = "feature/"


@dataclass(frozen=True)
class RuntimeFiles:
    project_dir: Path
    feature_dir: Path
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
    design: Path
    review: Path
    fix_request: Path
    changes: Path
    state: Path
    runtime_state: Path
    orchestrator_log: Path
