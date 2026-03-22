from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import AgentConfig, GitHubConfig, RuntimeFiles
from .runtime import AgentRuntime


EXIT_SUCCESS = "EXIT_SUCCESS"
EXIT_FAILURE = "EXIT_FAILURE"


@dataclass
class PipelineContext:
    files: RuntimeFiles
    runtime: AgentRuntime
    agents: dict[str, AgentConfig]
    max_review_iterations: int
    prompts: dict[str, Path]
    github_config: GitHubConfig = field(default_factory=GitHubConfig)
    entered_phase: str | None = None
    phase_baseline: dict[str, str | None] = field(default_factory=dict)


def file_signature(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def phase_input_changed(ctx: PipelineContext, key: str, current: str | None) -> bool:
    return current is not None and current != ctx.phase_baseline.get(key)
