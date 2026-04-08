"""MCP integration package.

This package handles MCP (Model Context Protocol) server configuration
for various AI provider CLIs (claude, codex, gemini, opencode).

Submodules:
    models: McpServerSpec data class and default constants
    configurators: Provider-specific persistent config management
    runtime: Runtime config generation and environment injection
    preparer: High-level facade for init/launcher flow
"""

from __future__ import annotations

# Configurators
from .configurators import (
    CONFIGURATORS,
    ClaudeConfigurator,
    CodexConfigurator,
    CopilotConfigurator,
    GeminiConfigurator,
    JsonMcpConfigurator,
    OpenCodeConfigurator,
    PersistentMcpConfigurator,
)

# Models
from .models import (
    DEFAULT_MCP_ROLES,
    DEFAULT_MCP_SERVERS,
    DEFAULT_RESEARCH_ROLES,
    DEFAULT_RESEARCH_SERVERS,
    McpServerSpec,
)

# Preparer
from .preparer import McpAgentPreparer, ensure_mcp_config

# Runtime
from .runtime import cleanup_mcp, create_runtime_mcp_config, setup_mcp

__all__ = [
    # Models
    "DEFAULT_MCP_ROLES",
    "DEFAULT_MCP_SERVERS",
    "DEFAULT_RESEARCH_ROLES",
    "DEFAULT_RESEARCH_SERVERS",
    "McpServerSpec",
    # Configurators
    "ClaudeConfigurator",
    "CodexConfigurator",
    "CopilotConfigurator",
    "CONFIGURATORS",
    "GeminiConfigurator",
    "JsonMcpConfigurator",
    "OpenCodeConfigurator",
    "PersistentMcpConfigurator",
    # Runtime
    "cleanup_mcp",
    "create_runtime_mcp_config",
    "setup_mcp",
    # Preparer
    "ensure_mcp_config",
    "McpAgentPreparer",
]
