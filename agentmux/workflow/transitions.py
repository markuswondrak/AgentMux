from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..runtime import AgentRuntime
from ..shared.models import AgentConfig, GitHubConfig, RuntimeFiles, WorkflowSettings

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
    workflow_settings: WorkflowSettings = field(default_factory=WorkflowSettings)
    entered_phase: str | None = None  # Keep for tracking, but not used for baseline
