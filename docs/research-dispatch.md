# Research Task Dispatch

> Related source files: `agentmux/mcp_research_server.py`, `agentmux/mcp_config.py`, `agentmux/pipeline.py`, `agentmux/defaults/config.yaml`, `agentmux/prompts.py`, `agentmux/prompts/agents/architect.md`, `agentmux/prompts/agents/product-manager.md`, `agentmux/prompts/agents/coder.md`

Research dispatch is now MCP-first. The architect and product-manager should call MCP tools to create research requests, then wait for AgentMux to push a completion message.

## MCP tools

The `agentmux-research` MCP server exposes:

- `agentmux_research_dispatch_code(topic, context, questions, feature_dir, scope_hints)`
- `agentmux_research_dispatch_web(topic, context, questions, feature_dir, scope_hints)`

Validation and behavior:

- `topic` must be a slug: lowercase alphanumeric words joined by `-` (for example `auth-module`)
- `questions` must include at least one non-empty item
- `feature_dir` should be the session directory shown in the architect or product-manager prompt
- `scope_hints` may be omitted, passed as a single string, or passed as a list of strings; list form is preferred
- dispatch writes `03_research/<type>-<topic>/request.md` with `## Context`, `## Questions`, and `## Scope hints`

Typical flow:

1. Dispatch one or more research topics (`code` and/or `web`).
2. Stop and wait idle. AgentMux will send the owner agent a completion message when each topic finishes.
3. Read `summary.md` first and `detail.md` only when needed.

Research completion stays file-driven: the orchestrator detects `done`, updates task state, and sends a follow-up message telling the owner agent which `summary.md` / `detail.md` files to read. AgentMux passes the active session directory explicitly as `feature_dir`, so the server does not rely on provider-specific environment propagation.

Completed research topics are also used for coder handoff: coder prompts include references to `03_research/<type>-<topic>/summary.md` (and `detail.md` when present) for topics that have a `done` marker.

## File protocol fallback

If MCP tools are unavailable, the legacy file protocol still works:

- Write `03_research/code-<topic>/request.md` or `03_research/web-<topic>/request.md`
- Wait for `03_research/<type>-<topic>/done`
- Read `summary.md` and optionally `detail.md`

Request files should include:

- `## Context`
- `## Questions`
- `## Scope hints`

## Provider setup strategy

AgentMux expects an MCP registration named `agentmux-research` for the effective `architect` and `product-manager` providers at the provider's native config scope:

- Claude: project `.claude/settings.json`
- Codex: user `~/.codex/config.toml`
- Gemini: project `.gemini/settings.json`
- OpenCode: project `opencode.json`

`agentmux init` and interactive pipeline startup prompt to create that entry only when it is missing. The registered command uses the current Python interpreter and launches `-m agentmux.mcp_research_server`.

For each run, AgentMux may inject `PYTHONPATH` into the launched `architect` / `product-manager` process so the MCP server can import the project checkout. Feature routing now comes from the `feature_dir` MCP tool argument.

For Claude, default launcher args allow MCP calls via `mcp__agentmux-research__*` in `--allowedTools`.
If the user declines setup, architect/product-manager should use the file-protocol fallback instead.
