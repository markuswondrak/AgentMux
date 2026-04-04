from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpServerSpec:
    """Provider-agnostic definition of an MCP server."""

    name: str
    module: str
    env: dict[str, str]


DEFAULT_RESEARCH_ROLES = ("architect", "product-manager")
DEFAULT_RESEARCH_SERVERS = (
    McpServerSpec(
        name="agentmux-research",
        module="agentmux.integrations.mcp_research_server",
        env={},
    ),
)
