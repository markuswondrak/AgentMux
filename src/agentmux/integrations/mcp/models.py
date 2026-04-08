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

# Backward-compat aliases
DEFAULT_RESEARCH_ROLES = DEFAULT_MCP_ROLES
DEFAULT_RESEARCH_SERVERS = DEFAULT_MCP_SERVERS
