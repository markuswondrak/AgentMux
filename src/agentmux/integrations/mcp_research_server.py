# Backward-compatibility shim — module was renamed to mcp_server.py
from agentmux.integrations.mcp_server import *  # noqa: F401, F403
from agentmux.integrations.mcp_server import mcp  # noqa: F401
