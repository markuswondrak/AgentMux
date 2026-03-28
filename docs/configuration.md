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

- **Use default provider for all roles** — keeps built-in role profile defaults and skips per-role provider/profile prompts
- **Customize roles** — preserves the original per-role provider/profile flow

After config validation, init checks the effective `architect` and `product-manager` providers. If their persistent `agentmux-research` MCP entry is missing, init asks once to add it to the provider's native config scope.

## Primary project config

The preferred project-level file is `.agentmux/config.yaml`:

```yaml
version: 1

defaults:
  session_name: multi-agent-mvp
  provider: claude
  profile: standard
  max_review_iterations: 3
  completion:
    skip_final_approval: false

github:
  base_branch: main
  draft: true
  branch_prefix: feature/

roles:
  architect:
    profile: max
  reviewer:
    profile: standard
  coder:
    provider: codex
    profile: standard
```

## Config structure

- `defaults.session_name` — tmux session name
- `defaults.provider` — default provider/launcher name for roles that do not override it
- `defaults.profile` — default profile name, usually `max`, `standard`, or `low`
- `defaults.max_review_iterations` — caps automatic reviewer→coder fix loops
- `defaults.completion.skip_final_approval` — when `true`, skips reviewer confirmation in `completing` and auto-prepares approval (default: `false`)
- `github.base_branch` — default PR base branch (default: `main`)
- `github.draft` — whether PRs created at completion are draft PRs by default (default: `true`)
- `github.branch_prefix` — prefix for completion branches created before opening a PR (default: `feature/`)
- `roles.<role>.provider` — optional provider override per role
- `roles.<role>.profile` — profile to resolve for that role
- `roles.<role>.args` — optional full override of the resolved CLI args for that role

Built-in and user-level configs may additionally define:

- `launchers.<name>.command` — CLI binary or wrapper command
- `launchers.<name>.model_flag` — model switch, default `--model`
- `launchers.<name>.trust_snippet` — auto-accept text for trust prompts
- `launchers.<name>.role_args.<role>` — default CLI args for a role
- `profiles.<provider>.<profile>.model` — concrete model name
- `profiles.<provider>.<profile>.args` — optional extra args appended after launcher role args

## Completion settings boundary

There is one runtime completion-settings owner: `workflow_settings.completion`.

- Config input maps directly into `defaults.completion.skip_final_approval`
- Runtime reads `workflow_settings.completion.skip_final_approval`

## Project vs user scope

Project config is intentionally limited to safe selection-level overrides. Auto-discovered project config may set `defaults` and `roles`, but it may not define `launchers` or `profiles`.

Custom CLIs, wrapper commands, trust snippets, and custom profile catalogs belong in user config or an explicit `--config` file.

Example user config:

```yaml
launchers:
  kimi:
    command: kimi
    model_flag: --model-name
    trust_snippet: Trust this folder?
    role_args:
      coder: [--sandbox, workspace-write]

profiles:
  kimi:
    low:
      model: kimi-2.5
```

After that, a project can safely select it:

```yaml
roles:
  coder:
    provider: kimi
    profile: low
```

## Strict schema

Unsupported legacy forms now fail fast:

- top-level role config outside `roles`
- top-level defaults such as `session_name`, `provider`, or `max_review_iterations`
- `defaults.skip_final_approval`
- `defaults.completion.require_final_approval`
- role `tier`

## Built-in profiles

| Profile | claude | codex | gemini | opencode |
|---------|--------|-------|--------|----------|
| max | `opus` | `gpt-5.4` | `gemini-2.5-pro` | `anthropic/claude-opus-4-6` |
| standard | `sonnet` | `gpt-5.3-codex` | `gemini-2.5-flash` | `anthropic/claude-sonnet-4-20250514` |
| low | `haiku` | `gpt-5.1-codex-mini` | `gemini-2.5-flash-lite` | `anthropic/claude-haiku-4-5-20251001` |

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

MCP setup for research now follows each provider's native config scope. `agentmux init` and foreground pipeline startup both check whether the effective `architect` / `product-manager` providers already have an `agentmux-research` entry in the correct location:

- Claude: project `.claude/settings.json`
- Codex: user `~/.codex/config.toml`
- Gemini: project `.gemini/settings.json`
- OpenCode: project `opencode.json`

When the entry is missing, the user is prompted to create or refresh it in that provider-specific file. Codex remains a user-scope prompt because Codex MCP servers are configured globally; the other bundled providers use repo-local project config.

At runtime, `setup_mcp(...)` no longer rewrites provider config. It only injects `PYTHONPATH=<project_dir>[...existing entries]` into the launched `architect` / `product-manager` process when needed so `agentmux.integrations.mcp_research_server` can import the project checkout. Research requests identify the active session explicitly via the `feature_dir` MCP tool argument.

Claude additionally needs explicit allowlisting, so defaults include `mcp__agentmux-research__*` in architect/product-manager `--allowedTools`. Other bundled providers already run in approval modes that auto-approve tool calls.
