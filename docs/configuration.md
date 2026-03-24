# Agent Configuration

> Related source files: `agentmux/config.py`, `agentmux/providers.py`, `agentmux/models.py`, `.agentmux/config.yaml`

## Overview

AgentMux now resolves agent configuration from layered config files instead of splitting user-facing settings across `pipeline_config.json` and hard-coded provider data in Python.

Resolution order:

1. Built-in defaults shipped in `agentmux/defaults/config.yaml`
2. User config in `~/.config/agentmux/config.yaml`
3. Project config in `.agentmux/config.yaml` (or `.yml` / `.json`)
4. Optional `--config <path>` override

Legacy `pipeline_config.json` is still supported as a project config and as an explicit `--config` input.

## Primary project config

The preferred project-level file is `.agentmux/config.yaml`:

```yaml
version: 1

defaults:
  session_name: multi-agent-mvp
  provider: claude
  profile: standard
  max_review_iterations: 3

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
  docs:
    profile: low
```

## Config structure

- `defaults.session_name` — tmux session name
- `defaults.provider` — default provider/launcher name for roles that do not override it
- `defaults.profile` — default profile name, usually `max`, `standard`, or `low`
- `defaults.max_review_iterations` — caps automatic reviewer→coder fix loops
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

## Legacy compatibility

The old schema is still accepted:

```json
{
  "session_name": "multi-agent-mvp",
  "provider": "claude",
  "architect": { "tier": "max" },
  "coder": { "provider": "codex", "tier": "standard" }
}
```

Compatibility rules:

- top-level `provider` maps to `defaults.provider`
- top-level `session_name` maps to `defaults.session_name`
- top-level `max_review_iterations` maps to `defaults.max_review_iterations`
- per-role `tier` is accepted as an alias for `profile`

## Built-in profiles

| Profile | claude | codex | gemini | opencode |
|---------|--------|-------|--------|----------|
| max | `opus` | `gpt-5.4` | `gemini-2.5-pro` | `anthropic/claude-opus-4-6` |
| standard | `sonnet` | `gpt-5.3-codex` | `gemini-2.5-flash` | `anthropic/claude-sonnet-4-20250514` |
| low | `haiku` | `gpt-5.1-mini` | `gemini-2.5-flash-lite` | `anthropic/claude-haiku-4-5-20251001` |

## Resolution

Each role resolves to an `AgentConfig` with:

- `cli`
- `model_flag`
- `model`
- `args`
- `trust_snippet`

The tmux runtime launches agents from that fully resolved config. The orchestrator still never talks to model APIs directly.
