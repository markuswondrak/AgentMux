# AgentMux

[![test](https://github.com/markuswondrak/AgentMux/actions/workflows/ci.yml/badge.svg)](https://github.com/markuswondrak/AgentMux/actions/workflows/ci.yml)

**Multi-agent software development pipelines using the AI CLI tools you already have.**

AgentMux orchestrates a structured workflow across multiple AI agents by driving existing CLI tools like `claude`, `codex`, `gemini`, and `opencode` through tmux. The pipeline owns the workflow; the agents execute focused role prompts against a shared file protocol.

---

<img width="1393" height="1075" alt="image" src="https://github.com/user-attachments/assets/094e01e5-8946-4b53-83bc-910a4c49968b" />

---

## How it works

The pipeline is static and deterministic. AgentMux moves work through planning, implementation, review, and completion phases by selecting the right role, rendering the right prompt, and injecting a prompt-file reference into that role's tmux pane.

Agents do not talk to each other directly. They coordinate through the session directory and the orchestrator's state machine.

## Architecture

The codebase is organized around component packages with clear ownership boundaries:

- `agentmux/pipeline/` — CLI entrypoint, init flow, and top-level application coordination
- `agentmux/workflow/` — phases, prompt rendering, transitions, orchestration, interruption policy
- `agentmux/runtime/` — tmux runtime control, event bus, file and interruption sources
- `agentmux/monitor/` — monitor command, state aggregation, terminal rendering
- `agentmux/integrations/` — GitHub, MCP research integration, completion side effects
- `agentmux/configuration/` — layered config loading, providers, defaults
- `agentmux/sessions/` — session preparation and persisted state
- `agentmux/terminal_ui/` — interactive console prompts and terminal layout helpers
- `agentmux/shared/` — shared models

## Quickstart

```bash
# Option 1: Install from GitHub
python3 -m pip install git+https://github.com/markuswondrak/AgentMux.git

# Option 2: Install isolated CLI with pipx
pipx install git+https://github.com/markuswondrak/AgentMux.git

# Update to latest main (pipx upgrade is unreliable for git installs)
pipx install --force git+https://github.com/markuswondrak/AgentMux.git

# Option 3: Editable install for local development
python3 -m pip install -e .

# Run a feature from description to reviewed, committed code
agentmux "Add rate limiting to the API"

# Optional: start with a product management phase
agentmux "Add rate limiting to the API" --product-manager

# Bootstrap from a GitHub issue
agentmux --issue 42
agentmux --issue https://github.com/owner/repo/issues/42

# Resume an interrupted run
agentmux --resume

```

For a detailed walkthrough, see the [Getting Started guide](docs/getting-started.md).

If `gh` is authenticated, AgentMux can bootstrap from issue content and open a pull request when the pipeline completes.

## Configuration

Project config lives in `.agentmux/config.yaml`. AgentMux resolves built-in defaults from `agentmux/configuration/defaults/config.yaml`, optional user config from `~/.config/agentmux/config.yaml`, then project config, with `--config <path>` as the final override.

```yaml
version: 1

defaults:
  provider: claude
  profile: standard
  completion:
    skip_final_approval: false

roles:
  architect:
    profile: max
  coder:
    provider: codex
    profile: standard
  reviewer:
    profile: standard
```

Profiles (`max`, `standard`, `low`) map to provider-specific models and launch arguments through the layered configuration system.

## Supported providers

- `claude` — Claude Code CLI
- `codex` — OpenAI Codex CLI
- `gemini` — Google Gemini CLI
- `opencode` — OpenCode CLI

## Agent roles

| Role | When active |
|------|-------------|
| `product-manager` | Optional first phase for requirements refinement |
| `architect` | Planning and replanning |
| `coder` | Implementation and fixes |
| `reviewer` | Review and final confirmation |
| `code-researcher` | On-demand codebase analysis |
| `web-researcher` | On-demand internet research |

## Requirements

- Python 3.10+
- tmux
- One or more supported AI CLI tools installed and authenticated

## Documentation

- [`docs/getting-started.md`](docs/getting-started.md) — installation, setup, and first pipeline run
- [`docs/configuration.md`](docs/configuration.md) — layered launcher/profile configuration
- [`docs/file-protocol.md`](docs/file-protocol.md) — shared file protocol between agents and orchestrator
- [`docs/monitor.md`](docs/monitor.md) — monitor command, state view, and terminal rendering
- [`docs/prompts.md`](docs/prompts.md) — built-in prompts and project prompt extensions
- [`docs/tmux-layout.md`](docs/tmux-layout.md) — session layout and pane lifecycle
- [`docs/research-dispatch.md`](docs/research-dispatch.md) — code and web researcher dispatch
- [`docs/completing-phase.md`](docs/completing-phase.md) — approval flow and completion side effects
- [`docs/session-resumption.md`](docs/session-resumption.md) — resuming interrupted pipelines
