# Research Task Dispatch

> Related source files: `agentmux/mcp_research_server.py`, `agentmux/mcp_config.py`, `agentmux/pipeline.py`, `agentmux/defaults/config.yaml`, `agentmux/prompts/agents/architect.md`, `agentmux/prompts/agents/product-manager.md`

Research dispatch is now MCP-first. The architect and product-manager should call MCP tools to create research requests and await results.

## MCP tools

The `agentmux-research` MCP server exposes:

- `agentmux_research_dispatch_code(topic, context, questions, scope_hints)`
- `agentmux_research_dispatch_web(topic, context, questions, scope_hints)`
- `agentmux_research_await(topic, research_type, detail=false, timeout=300)`

Validation and behavior:

- `topic` must be a slug: lowercase alphanumeric words joined by `-` (for example `auth-module`)
- `questions` must include at least one non-empty item
- `research_type` must be `"code"` or `"web"`
- dispatch writes `research/<type>-<topic>/request.md` with `## Context`, `## Questions`, and `## Scope hints`
- await returns `"No research task found. Did you dispatch it first?"` when the topic directory is missing
- await returns `"Research on '<topic>' timed out after <timeout>s."` on timeout
- await returns `summary.md` by default, or `detail.md` when `detail=true` (with a clear missing-file message if absent)

Typical flow:

1. Dispatch one or more research topics (`code` and/or `web`).
2. Await each topic with `agentmux_research_await`.
3. Use `detail=true` when full findings are required.

`agentmux_research_await` blocks until the corresponding `done` marker exists (or timeout), so agents do not need polling loops.
The server requires `FEATURE_DIR` in its environment so requests map to the active session directory.

## File protocol fallback

If MCP tools are unavailable, the legacy file protocol still works:

- Write `research/code-<topic>/request.md` or `research/web-<topic>/request.md`
- Wait for `research/<type>-<topic>/done`
- Read `summary.md` and optionally `detail.md`

Request files should include:

- `## Context`
- `## Questions`
- `## Scope hints`

## Provider injection strategy

The pipeline injects the same MCP server for `architect` and `product-manager` across providers:

- Claude: `--mcp-config <feature_dir>/mcp_claude.json`
- Codex: `CODEX_HOME=<feature_dir>/codex_home` (staged `config.toml` with `mcp_servers` blocks)
- Gemini: project `.gemini/settings.json` only when absent (skip injection if user config exists)
- OpenCode: `OPENCODE_CONFIG=<feature_dir>/mcp_opencode.json`

For Claude, default launcher args allow MCP calls via `mcp__agentmux-research__*` in `--allowedTools`.
Gemini cleanup removes generated project config only when the pipeline created it (tracked via marker file in the feature directory).
Cleanup runs during orchestrator shutdown.
