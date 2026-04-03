# GitHub Copilot CLI Provider Integration Plan

## Overview

This document outlines the implementation plan for adding GitHub Copilot CLI (`copilot`) as a new provider to the Agentmux multi-agent orchestration system.

## Problem Analysis

**Goal**: Integrate GitHub Copilot CLI as a first-class provider alongside existing providers (claude, codex, gemini, opencode).

**Key Requirements**:
1. Provider definition in the built-in configuration
2. CLI tool detection during project initialization
3. Trust prompt handling for Copilot's security prompts
4. Role-specific argument configuration
5. Documentation updates

**Technical Context**:
- Command: `copilot` (from npm package `@github/copilot`)
- Model Flag: `--model=<model>` (e.g., `--model=gpt-4o`, `--model=claude-sonnet-4`)
- Trust Snippet: "trust the files" (for auto-accepting trust prompts)
- Permission Flags: `--allow-all` or `--yolo` for non-interactive mode
- Prompt Mode: `-p "prompt"` or `--prompt="prompt"`

## Architecture Design

### Provider Configuration Schema

The Copilot provider follows the existing v2 config schema:

```yaml
providers:
  copilot:
    command: copilot           # CLI binary name
    model_flag: --model        # Model selection flag
    trust_snippet: "trust the files"  # Auto-accept trust prompts
    role_args:                 # Default args per role
      <role>: [<args>]
```

### Permission Strategy

Copilot CLI requires explicit permissions for autonomous operation:

| Flag | Purpose |
|------|---------|
| `--allow-all` | Enable all permissions (tools, paths, URLs) |
| `--yolo` | Alias for `--allow-all` |
| `--allow-all-tools` | Allow all tools without confirmation |
| `--allow-all-paths` | Disable file path verification |

For Agentmux workflows, we use `--allow-all` to ensure non-interactive operation.

### Model Resolution

Copilot supports multiple models:
- `gpt-4o` (default)
- `claude-sonnet-4`
- `o3-mini`
- `gemini-2.5-flash`

Models are specified via `--model=<model>` flag.

## Implementation Steps

### Phase 1: Provider Definition

**File**: `agentmux/configuration/defaults/config.yaml`

Add the copilot provider definition after the opencode provider:

```yaml
  copilot:
    command: copilot
    model_flag: --model
    trust_snippet: trust the files
    role_args:
      architect:
        - --allow-all
      product-manager:
        - --allow-all
      reviewer:
        - --allow-all
      coder:
        - --allow-all
      designer:
        - --allow-all
      code-researcher:
        - --allow-all
      web-researcher:
        - --allow-all
      reviewer_expert:
        - --allow-all
      reviewer_logic:
        - --allow-all
      reviewer_quality:
        - --allow-all
```

### Phase 2: CLI Detection

**File**: `agentmux/pipeline/init_command.py`

1. Update `KNOWN_PROVIDERS` tuple (line ~37):

```python
KNOWN_PROVIDERS = ("claude", "codex", "gemini", "opencode", "copilot")
```

2. Update error messages (lines ~324 and ~661):

```python
# Line 324
"Install one of: claude, codex, gemini, opencode, copilot."

# Line 661  
"Install one of: claude, codex, gemini, opencode, copilot."
```

### Phase 3: Documentation Updates

**File**: `docs/configuration.md`

1. Add copilot to the provider examples section
2. Add installation note: `npm install -g @github/copilot`
3. Add example configuration:

```yaml
version: 2
defaults:
  provider: copilot
  model: gpt-4o
roles:
  architect:
    model: claude-sonnet-4
  coder:
    model: gpt-4o
```

### Phase 4: Testing Checklist

- [ ] `agentmux init` detects `copilot` CLI
- [ ] Config validation accepts `provider: copilot`
- [ ] Tmux runtime starts `copilot` correctly
- [ ] Trust prompts are auto-accepted
- [ ] Model selection works via `--model` flag
- [ ] All roles receive correct `--allow-all` argument

## Configuration Examples

### Basic Usage

```yaml
version: 2
defaults:
  provider: copilot
  model: gpt-4o
```

### Per-Role Model Selection

```yaml
version: 2
defaults:
  provider: copilot
  model: gpt-4o
roles:
  architect:
    model: claude-sonnet-4
  reviewer_expert:
    model: o3-mini
```

### Mixed Provider Setup

```yaml
version: 2
defaults:
  provider: claude
  model: sonnet
roles:
  coder:
    provider: copilot
    model: gpt-4o
  web-researcher:
    provider: copilot
    model: gpt-4o
```

## Environment Variables

Copilot CLI supports these relevant environment variables:

| Variable | Description |
|----------|-------------|
| `COPILOT_ALLOW_ALL` | Set to `true` to allow all permissions |
| `COPILOT_MODEL` | Default model selection |
| `COPILOT_GITHUB_TOKEN` | Authentication token |
| `COPILOT_HOME` | Config directory (default: `~/.copilot`) |

## Notes

### Trust Prompt Handling

Copilot CLI asks "Do you trust the files in this folder?" on first run. The `trust_snippet: "trust the files"` configuration enables Agentmux to auto-accept this prompt by sending "Yes, proceed" (or just Enter for default option).

### MCP Server Support

Copilot CLI has built-in MCP support via `/mcp` commands. The `agentmux-research` MCP server can potentially be integrated, but this is out of scope for the initial provider implementation.

### Custom Agents

Copilot supports custom agents via `--agent=<agent>` flag. This could be leveraged in future enhancements to map Agentmux roles to Copilot custom agents.

## References

- [GitHub Copilot CLI Documentation](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli)
- [Copilot CLI Command Reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)
- [Installing Copilot CLI](https://docs.github.com/en/copilot/managing-copilot/configure-personal-settings/installing-github-copilot-in-the-cli)
