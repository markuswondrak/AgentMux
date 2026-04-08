# Research Task Dispatch

> Related source files: `agentmux/integrations/mcp_server.py`, `agentmux/integrations/mcp.py`, `agentmux/pipeline/application.py`, `agentmux/configuration/defaults/config.yaml`, `agentmux/workflow/prompts.py`, `agentmux/prompts/agents/architect.md`, `agentmux/prompts/agents/product-manager.md`, `agentmux/prompts/agents/coder.md`

Research dispatch is now MCP-first. The architect and product-manager should call MCP tools to create research requests, then wait for AgentMux to push a completion message.

## MCP tools

The `agentmux-research` MCP server exposes research dispatch tools and structured submission tools.

### Research dispatch

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
3. Read `summary.md` first. `detail.md` remains available when deeper implementation context is needed.

Research completion stays file-driven: the orchestrator detects `done`, updates task state, and sends a follow-up message pointing the owner agent to `summary.md`. `detail.md` remains available as a secondary artifact. AgentMux passes the active session directory explicitly as `feature_dir`, so the server does not rely on provider-specific environment propagation.

Completed research topics are also used for coder handoff: coder prompts include references to `03_research/<type>-<topic>/summary.md` (and `detail.md` when present) for topics that have a `done` marker.

### Structured submission tools

The same MCP server also provides four submission tools for structured agent handoffs:

- `agentmux_submit_architecture` — validates and writes `architecture.yaml` + `architecture.md`
- `agentmux_submit_execution_plan` — validates and writes `execution_plan.yaml` + `plan.md`
- `agentmux_submit_subplan` — validates and writes `plan_N.yaml` + `plan_N.md` + `tasks_N.md`
- `agentmux_submit_review` — validates and writes `review.yaml` + `review.md`

These tools validate input against handoff contracts defined in `agentmux/workflow/handoff_contracts.py`. See `docs/handoff-contracts.md` for full contract details.

## Provider setup strategy

AgentMux expects an MCP registration named `agentmux-research` for the effective `architect` and `product-manager` providers at the provider's native config scope:

- Claude: project `.claude/settings.json`
- Codex: user `~/.codex/config.toml`
- Gemini: project `.gemini/settings.json`
- OpenCode: project `opencode.json`

`agentmux init` and interactive pipeline startup prompt to create that entry only when it is missing. The registered command uses the current Python interpreter and launches `-m agentmux.integrations.mcp_server`.

For each run, AgentMux may inject `PYTHONPATH` into the launched `architect` / `product-manager` process so the MCP server can import the project checkout. Feature routing now comes from the `feature_dir` MCP tool argument.

For Claude, default provider args allow MCP calls via `mcp__agentmux-research__*` in `--allowedTools`.
