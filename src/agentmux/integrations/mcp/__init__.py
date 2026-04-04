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
    GeminiConfigurator,
    JsonMcpConfigurator,
    OpenCodeConfigurator,
    PersistentMcpConfigurator,
)

# Models
from .models import (
    DEFAULT_RESEARCH_ROLES,
    DEFAULT_RESEARCH_SERVERS,
    McpServerSpec,
)

# Runtime
from .runtime import cleanup_mcp, create_runtime_mcp_config, setup_mcp

# Backward-compat alias for renamed function
_create_runtime_mcp_config = create_runtime_mcp_config

# Preparer
# Re-export OPENCODE_AGENT_ROLES from shared.models for backward compatibility
from ...shared.models import OPENCODE_AGENT_ROLES as OPENCODE_AGENT_ROLES

# OpenCode agent configurator (separate domain, re-exported for backward compat)
from ..opencode_agents import (
    OPENCODE_AGENT_PERSONAS as OPENCODE_AGENT_PERSONAS,
)
from ..opencode_agents import (
    OpenCodeAgentConfigurator as OpenCodeAgentConfigurator,
)
from .preparer import McpAgentPreparer, ensure_mcp_config

__all__ = [
    # Models
    "DEFAULT_RESEARCH_ROLES",
    "DEFAULT_RESEARCH_SERVERS",
    "McpServerSpec",
    # Configurators
    "ClaudeConfigurator",
    "CodexConfigurator",
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
    # Backward compat
    "OPENCODE_AGENT_ROLES",
]
