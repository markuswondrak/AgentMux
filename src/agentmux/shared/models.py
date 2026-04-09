from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .phase_catalog import SESSION_DIR_NAMES as SESSION_DIR_NAMES  # noqa: F401

PROMPT_AGENT_ROLES: tuple[str, ...] = (
    "architect",
    "code-researcher",
    "coder",
    "designer",
    "planner",
    "product-manager",
    "reviewer",
    "reviewer_expert",
    "reviewer_logic",
    "reviewer_quality",
    "web-researcher",
)

# The 8 primary pipeline roles that get their own opencode agent entries.
# Excludes reviewer sub-roles (reviewer_expert/logic/quality) since they
# share the reviewer role's agent entry.
OPENCODE_AGENT_ROLES: tuple[str, ...] = (
    "architect",
    "planner",
    "product-manager",
    "reviewer",
    "coder",
    "designer",
    "code-researcher",
    "web-researcher",
)

BATCH_AGENT_ROLES: frozenset[str] = frozenset({"code-researcher", "web-researcher"})


@dataclass(frozen=True)
class AgentConfig:
    role: str
    cli: str
    model: str
    model_flag: str | None = "--model"
    args: list[str] | None = None
    env: dict[str, str] | None = None
    trust_snippet: str | None = None
    provider: str | None = None
    batch_subcommand: str | None = None
    single_coder: bool = False


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
    architecture: Path
    tasks: Path
    execution_plan: Path
    design: Path
    review: Path
    fix_request: Path
    changes: Path
    summary: Path
    state: Path
    runtime_state: Path
    orchestrator_log: Path
    created_files_log: Path
    status_log: Path
    # Specialized reviewer prompt paths (for review_strategy routing)
    review_logic_prompt: Path | None = None
    review_quality_prompt: Path | None = None
    review_expert_prompt: Path | None = None

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.feature_dir).as_posix()


def tasks_file_for_plan(planning_dir: Path, plan_index: int) -> Path:
    """Return the path to the per-plan tasks file for a given plan index.

    The naming convention is `tasks_<N>.md` aligned with `plan_<N>.md`.
    This allows each sub-plan to have its own implementation checklist,
    while the global tasks.md remains available as an optional overview.

    Args:
        planning_dir: The 02_planning directory path.
        plan_index: The sub-plan index (1-based for first sub-plan).

    Returns:
        The path to the per-plan tasks file (e.g., tasks_1.md).
    """
    return planning_dir / f"tasks_{plan_index}.md"


@dataclass(frozen=True)
class ProjectPaths:
    """Canonical container for project-level file paths.

    Binds the project root once and provides derived path attributes,
    eliminating scattered inline path construction.
    """

    project_dir: Path

    @property
    def root(self) -> Path:
        return self.project_dir / ".agentmux"

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def mcp_servers(self) -> Path:
        return self.root / "mcp_servers.json"

    @property
    def sessions_root(self) -> Path:
        return self.root / ".sessions"

    @property
    def last_completion(self) -> Path:
        return self.root / ".last_completion.json"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def agent_prompts_dir(self) -> Path:
        return self.prompts_dir / "agents"

    @property
    def command_prompts_dir(self) -> Path:
        return self.prompts_dir / "commands"

    @staticmethod
    def from_project(project_dir: Path) -> ProjectPaths:
        """Create a ProjectPaths instance from a project directory."""
        return ProjectPaths(project_dir=project_dir)
