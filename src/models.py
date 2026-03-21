from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    role: str
    cli: str
    model: str
    args: list[str] = None


@dataclass(frozen=True)
class RuntimeFiles:
    project_dir: Path
    feature_dir: Path
    context: Path
    requirements: Path
    plan: Path
    design: Path
    review: Path
    fix_request: Path
    changes: Path
    state: Path
    orchestrator_log: Path
