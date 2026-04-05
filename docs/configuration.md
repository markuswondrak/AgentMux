# Agent Configuration

> Related source files: `agentmux/configuration/__init__.py`, `agentmux/configuration/providers.py`, `agentmux/pipeline/init_command.py`, `agentmux/integrations/mcp.py`, `agentmux/shared/models.py`, `agentmux/configuration/defaults/config.yaml`, `.agentmux/config.yaml`

## Overview

AgentMux resolves agent configuration from layered config files only.

Resolution order:

1. Built-in defaults shipped in `agentmux/configuration/defaults/config.yaml`
2. User config in `~/.config/agentmux/config.yaml`
3. Project config in `.agentmux/config.yaml` (or `.yml` / `.json`)
4. Optional `--config <path>` override

## Project Initialization

Use `agentmux init` to scaffold a new project with configuration:

- **Interactive mode** — Guides you through a quick setup or custom role assignments, GitHub settings, optional MCP setup, and optional prompt stubs
- **Non-interactive mode** (`--defaults`) — Creates config with built-in defaults and CLAUDE.md template
- **CLI detection** — Automatically detects installed providers (claude, codex, gemini, opencode, copilot)
- **Config generation** — Creates `.agentmux/config.yaml` with only necessary overrides (minimal config files)
- **CLAUDE.md setup** — Creates a template, symlinks an existing file, or skips
- **Prompt stubs** — Optionally generates role-specific instruction files in `.agentmux/prompts/agents/`

Interactive init first asks for a default provider, then offers:

- **Use default provider for all roles** — keeps built-in role defaults and skips per-role provider/model prompts
- **Customize roles** — prompts for per-role provider and model

After config validation, init checks the effective `architect` and `product-manager` providers. If their persistent `agentmux-research` MCP entry is missing, init asks once to add it to the provider's native config scope.

## Primary project config

The preferred project-level file is `.agentmux/config.yaml`:

```yaml
version: 2

defaults:
  session_name: multi-agent-mvp
  provider: claude
  model: sonnet
  max_review_iterations: 3
  completion:
    skip_final_approval: false

github:
  base_branch: main
  draft: true
  branch_prefix: feature/

roles:
  architect:
    model: opus
  reviewer:
    model: sonnet
  coder:
    provider: codex
    model: gpt-5.3-codex
```

## Config structure

- `version` — **Required**. Must be `2` for new configs. Configs without `version` or with `version: 1` will fail with a helpful migration message.
- `defaults.session_name` — legacy fallback used only when resuming old sessions that do not yet persist `state.json.session_name`; new runs derive tmux names from the feature directory (`agentmux-<feature_dir_name>`)
- `defaults.provider` — default provider name for roles that do not override it
- `defaults.model` — default model name (e.g., `sonnet`, `opus`, `gpt-5.3-codex`)
- `defaults.max_review_iterations` — caps automatic reviewer→coder fix loops
- `defaults.completion.skip_final_approval` — when `true`, skips reviewer confirmation in `completing` and auto-prepares approval (default: `false`)
- `github.base_branch` — default PR base branch (default: `main`)
- `github.draft` — whether PRs created at completion are draft PRs by default (default: `true`)
- `github.branch_prefix` — prefix for completion branches created before opening a PR (default: `feature/`)
- `roles.<role>.provider` — optional provider override per role
- `roles.<role>.model` — model name for that role (direct model selection, no profiles)
- `roles.<role>.args` — optional full override of the resolved CLI args for that role

Built-in and user-level configs may additionally define:

- `providers.<name>.command` — CLI binary or wrapper command
- `providers.<name>.model_flag` — model switch, default `--model`
- `providers.<name>.trust_snippet` — auto-accept text for trust prompts
- `providers.<name>.role_args.<role>` — default CLI args for a role
- `providers.<name>.single_coder` — when `true`, the implementing phase sends one combined prompt covering all sub-plans to a single coder pane instead of spawning parallel/serial panes. The coder is expected to use its own internal sub-agents. Default: `false`.

## Completion settings boundary

There is one runtime completion-settings owner: `workflow_settings.completion`.

- Config input maps directly into `defaults.completion.skip_final_approval`
- Runtime reads `workflow_settings.completion.skip_final_approval`

## Project vs user scope

Project config can define `defaults`, `roles`, `github`, and now also `providers` (in v2). This allows teams to ship complete project-specific configurations.

User config can define `defaults`, `roles`, `github`, and `providers`.

Example user config:

```yaml
version: 2
providers:
  kimi:
    command: kimi
    model_flag: --model-name
    trust_snippet: Trust this folder?
    role_args:
      coder: [--sandbox, workspace-write]
```

After that, a project can safely select it:

```yaml
version: 2
roles:
  coder:
    provider: kimi
    model: kimi-2.5
```

## GitHub Copilot CLI provider

`copilot` (from `npm install -g @github/copilot`) is a built-in provider. Install the CLI, then select it as the default provider or per role:

```yaml
version: 2
defaults:
  provider: copilot
  model: claude-sonnet-4.6
```

Per-role model selection:

```yaml
version: 2
defaults:
  provider: copilot
  model: claude-sonnet-4.6
roles:
  architect:
    model: claude-opus-4.6
  reviewer_expert:
    model: gpt-5.4
```

Supported models: `claude-sonnet-4.6`, `claude-opus-4.6`, `gpt-5.4`, `gemini-2.5-pro`. Models are selected via `--model=<model>`.

`copilot` uses `--allow-all` and `--reasoning-effort high` for all roles to enable non-interactive operation with maximum reasoning capability. On first run in a directory, Copilot CLI asks "Do you trust the files in this folder?" — Agentmux auto-accepts this via the `trust_snippet: "trust the files"` configuration.

### Provider default settings

Providers can define `default_model` and `default_role_args` that apply to all roles automatically:

```yaml
version: 2
providers:
  my-provider:
    command: my-cli
    model_flag: --model
    default_model: my-default-model
    default_role_args:
    - --shared-flag
    - shared-value
    role_args:
      coder:
      - --coder-specific
```

In this example, the `coder` role receives both `[--shared-flag, shared-value, --coder-specific]`. The copilot provider uses this pattern to set `claude-sonnet-4.6` as the default model and `[--allow-all, --reasoning-effort, high]` as default args for all roles.

### Single-coder mode

`copilot` has `single_coder: true` set in its built-in provider config. This means the implementing phase sends **one combined prompt** to a single copilot pane instead of spawning separate panes for each sub-plan. The prompt embeds all plan and tasks content, and instructs copilot to use its own internal sub-agents to implement each plan. Copilot writes the `done_N` completion marker files as each plan finishes (or all at once at the end).

When the coder provider is `copilot` with `single_coder: true`, the `/fleet` slash command is automatically sent as keystrokes before the prompt file reference. This tells Copilot CLI to decompose the embedded plan into sub-agent tasks and execute them in parallel, with the main copilot instance acting as orchestrator. The `/fleet` command is sent interactively (not embedded in the prompt file) because Copilot CLI only recognizes slash commands when entered as direct input. The prefix is applied transparently — no extra config flag is needed.

This design avoids multiple premium-request invocations (one per sub-plan pane) in favour of a single invocation where copilot manages parallelism internally via `/fleet`.

The `single_coder` flag can also be set on any custom provider definition in user or project config:

```yaml
version: 2
providers:
  my-provider:
    command: my-cli
    model_flag: --model
    single_coder: true
    role_args:
      coder: [--allow-all]
```

Note: The automatic `/fleet` prefix command is only sent when the coder's provider is `copilot`. Other providers with `single_coder: true` receive the combined prompt without the prefix command.

## Strict schema

Unsupported legacy forms now fail fast:

- `profile` key (use `model` directly)
- `launchers:` key (renamed to `providers:`)
- `profiles:` section (removed entirely)
- top-level role config outside `roles`
- top-level defaults such as `session_name`, `provider`, or `max_review_iterations`
- `defaults.skip_final_approval`
- `defaults.completion.require_final_approval`
- role `tier`

## Migration from v1 to v2

If you have an existing v1 config, you'll see an error like:

```
Legacy config detected (version: 1). Please migrate to version: 2.
- Rename 'launchers:' to 'providers:'
- Replace 'profile: <name>' with 'model: <model-name>'
- Remove 'profiles:' section
```

To migrate:

1. Change `version: 1` to `version: 2`
2. Rename `launchers:` to `providers:`
3. Replace `profile: <profile_name>` with `model: <model_name>` directly
4. Remove the entire `profiles:` section
5. Remove any custom profiles you defined (models are now specified directly)

Example migration:

```yaml
# v1 config
version: 1
defaults:
  provider: claude
  profile: standard
roles:
  architect:
    profile: max
  coder:
    provider: codex
    profile: standard

# Becomes v2 config
version: 2
defaults:
  provider: claude
  model: sonnet
roles:
  architect:
    model: opus
  coder:
    provider: codex
    model: gpt-5.3-codex
```

## Resolution

Each role resolves to an `AgentConfig` with:

- `cli`
- `model_flag`
- `model`
- `args`
- `env` (optional runtime environment variables to prepend via `env KEY=VALUE ...`)
- `trust_snippet`

The tmux runtime launches agents from that fully resolved config. AgentMux still never talks to model APIs directly.

## OpenCode provider: model configuration caveat

When using the `opencode` provider with `--agent`, opencode **ignores** the `--model` flag entirely. The model is determined solely by the `agent.<agent-name>.model` entry in `opencode.json`.

AgentMux detects this mismatch at startup: if `model:` is configured for an opencode role in agentmux config, a warning is printed to stderr and the user is prompted to choose:

- **[a]** Add the configured model to `opencode.json` for the matching agent, then continue (AgentMux updates the file automatically)
- **[y]** Continue without updating `opencode.json` (the model from `opencode.json` will be used)
- **[n]** Abort (default)

To configure which model opencode uses, set it in `opencode.json`:

```json
{
  "agent": {
    "agentmux-coder": {
      "model": "qwen3"
    }
  }
}
```

The warning shows the full picture: what was configured in agentmux, what will actually happen, and how to fix it.

## Runtime MCP setup for research tools

MCP setup for research uses a **two-layer configuration approach** that separates persistent project-level config from runtime-generated config.

### Persistent config (project-level)

`agentmux init` and foreground pipeline startup check whether the effective `architect` / `product-manager` providers already have an `agentmux-research` entry in the provider's native config location:

- Claude: project `.claude/settings.json`
- Codex: user `~/.codex/config.toml`
- Gemini: project `.gemini/settings.json`
- OpenCode: project `opencode.json`

When the entry is missing, the user is prompted to create or refresh it. This persistent config serves as a fallback for manual CLI tool usage outside the pipeline.

**Idempotent behavior**: The setup process compares existing server entries to the generated entry before writing. If the configuration is unchanged, the file is not modified. This prevents unnecessary writes that could invalidate MCP approval caches. The comparison checks the `type`, `command`, and `args` fields to determine if an update is needed.

### Runtime config (generated at startup)

At pipeline startup, a runtime MCP config file is generated at `.agentmux/mcp_servers.json` inside the project directory. This file contains:

```json
{
  "mcpServers": {
    "agentmux-research": {
      "type": "stdio",
      "command": "/path/to/python",
      "args": ["-m", "agentmux.integrations.mcp_research_server"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/project"
      }
    }
  }
}
```

**Key characteristics**:
- Contains absolute paths specific to the current environment
- Generated fresh on each pipeline run
- Passed to Claude via the `--mcp-config <path>` command-line flag
- Not meant to be committed to version control (runtime artifact)
- Content is compared before writing to avoid unnecessary updates

### Runtime injection

For Claude agents, the pipeline appends `["--mcp-config", ".agentmux/mcp_servers.json"]` to the launch arguments. This bypasses project-level settings trust requirements by explicitly providing the MCP server configuration at runtime.

For other providers (Codex, Gemini, OpenCode), the pipeline only injects `PYTHONPATH=<project_dir>` into the launched process environment so the research server can import the project checkout.

Claude additionally needs explicit tool allowlisting, so defaults include `mcp__agentmux-research__*` in architect/product-manager `--allowedTools`. Other bundled providers run in approval modes that auto-approve tool calls.
