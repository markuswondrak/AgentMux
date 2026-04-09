from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpServerSpec:
    """Provider-agnostic definition of an MCP server."""

    name: str
    module: str
    env: dict[str, str]


DEFAULT_MCP_ROLES = (
    "architect",
    "product-manager",
    "planner",
    "coder",
    "code-researcher",
    "web-researcher",
    "reviewer_logic",
    "reviewer_quality",
    "reviewer_expert",
)
DEFAULT_MCP_SERVERS = (
    McpServerSpec(
        name="agentmux-research",
        module="agentmux.integrations.mcp_server",
        env={},
    ),
)

# Maps each role to the exact MCP tools it is allowed to call.
# Only tools listed here will be registered when the MCP server is spawned
# for that role (via AGENTMUX_ALLOWED_TOOLS env var).
ROLE_TOOLS: dict[str, tuple[str, ...]] = {
    "architect": (
        "research_dispatch_code",
        "research_dispatch_web",
        "submit_architecture",
    ),
    "product-manager": (
        "research_dispatch_code",
        "research_dispatch_web",
        "submit_pm_done",
    ),
    "planner": (
        "research_dispatch_code",
        "research_dispatch_web",
        "submit_plan",
    ),
    "coder": ("submit_done",),
    "code-researcher": ("submit_research_done",),
    "web-researcher": ("submit_research_done",),
    "reviewer": ("submit_review",),
    "reviewer_logic": ("submit_review",),
    "reviewer_quality": ("submit_review",),
    "reviewer_expert": ("submit_review",),
}

# Backward-compat aliases
DEFAULT_RESEARCH_ROLES = DEFAULT_MCP_ROLES
DEFAULT_RESEARCH_SERVERS = DEFAULT_MCP_SERVERS
