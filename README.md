# AgentMux

[![test](https://github.com/markuswondrak/AgentMux/actions/workflows/ci.yml/badge.svg)](https://github.com/markuswondrak/AgentMux/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Run a full multi-agent software pipeline using the AI subscriptions you already have.**

AgentMux orchestrates a structured PM → Architect → Plan → Code → Review → Done workflow across `claude`, `codex`, `gemini`, and `opencode` — driving them through tmux, not the API. No pay-per-token. No new credentials. Just your existing CLI tools working in concert.

---
<img width="1595" height="1071" alt="agentmux" src="https://github.com/user-attachments/assets/806e0fe8-decc-4869-80be-35f99f03481b" />
---

## Why AgentMux

- **No API costs** — injects prompts into tmux panes, reusing your existing Claude, Codex, Gemini, or OpenCode subscriptions. No tokens billed to you directly.
- **Structured pipeline** — a deterministic state machine moves work through planning, implementation, and review phases. Agents don't freelance; they execute focused roles.
- **Mix providers per role** — run the architect on Claude Max, the coder on Codex, and the reviewer on Gemini. Each role is independently configurable.
- **Watch it work** — the session is a live tmux window. Attach at any time to observe, intervene, or take over.
- **GitHub-native** — bootstrap from an issue, auto-open a pull request when the pipeline completes.

## Quickstart

```bash
# Install with pipx (recommended)
pipx install git+https://github.com/markuswondrak/AgentMux.git

# Initialize a project (interactive setup)
cd your-repo
agentmux init

# Run a feature from description to reviewed, committed code
agentmux "Add rate limiting to the API"

# Bootstrap from a GitHub issue
agentmux issue 42

# Resume an interrupted run
agentmux resume
```

For a full walkthrough, see the [Getting Started guide](docs/getting-started.md).

## How it works

AgentMux creates a tmux session with a control pane and one pane per agent role. A file-watching orchestrator tracks session artifacts written by agents and advances the workflow state machine when the right files appear. Agents coordinate through a shared file protocol — they never talk to each other directly. The orchestrator decides what happens next and injects the appropriate prompt into the right pane.

## Configuration

Project config lives in `.agentmux/config.yaml`. Run `agentmux init` to scaffold it interactively, or create it manually:

```yaml
version: 2

defaults:
  provider: claude
  model: sonnet

roles:
  architect:
    model: opus
  coder:
    provider: codex
  reviewer:
    model: sonnet
```

Config is resolved in layers: built-in defaults → `~/.config/agentmux/config.yaml` → project config → `--config <path>`. See [`docs/configuration.md`](docs/configuration.md) for the full schema.

## Supported providers

| Provider | CLI tool |
|----------|----------|
| `claude` | Claude Code CLI |
| `codex` | OpenAI Codex CLI |
| `gemini` | Google Gemini CLI |
| `opencode` | OpenCode CLI |

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
- [`docs/configuration.md`](docs/configuration.md) — layered config schema, providers, and model selection
- [`docs/file-protocol.md`](docs/file-protocol.md) — shared file protocol between agents and orchestrator
- [`docs/monitor.md`](docs/monitor.md) — monitor command, state view, and terminal rendering
- [`docs/prompts.md`](docs/prompts.md) — built-in prompts and project prompt extensions
- [`docs/tmux-layout.md`](docs/tmux-layout.md) — session layout and pane lifecycle
- [`docs/research-dispatch.md`](docs/research-dispatch.md) — code and web researcher dispatch
- [`docs/completing-phase.md`](docs/completing-phase.md) — approval flow and completion side effects
- [`docs/session-resumption.md`](docs/session-resumption.md) — resuming interrupted pipelines
