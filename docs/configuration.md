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
- **CLI detection** — Automatically detects installed providers (claude, codex, gemini, opencode)
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
