# Getting Started

This guide walks through a first-time setup of AgentMux: prerequisites, installation, `agentmux init`, and a first pipeline run.

## Prerequisites Checklist

Before you run AgentMux, verify each prerequisite:

- Python 3.10+
  ```bash
  python3 --version
  ```
- tmux
  ```bash
  tmux -V
  ```
- At least one supported CLI tool (`claude`, `codex`, `gemini`, or `opencode`)
  ```bash
  claude --version
  codex --version
  gemini --version
  opencode --version
  ```

Your chosen CLI tool must also be authenticated before running pipelines.

## Installation

Choose one install path:

1. Install from GitHub with pip
   ```bash
   python3 -m pip install git+https://github.com/markuswondrak/AgentMux.git
   ```
2. Install as an isolated CLI with pipx
   ```bash
   pipx install git+https://github.com/markuswondrak/AgentMux.git
   ```
3. Upgrade a pipx Git install (recommended pattern for this repo)
   ```bash
   pipx install --force git+https://github.com/markuswondrak/AgentMux.git
   ```
4. Editable install for local development
   ```bash
   python3 -m pip install -e .
   ```

Verify the CLI is available:

```bash
agentmux --help
```

## Project Setup (`agentmux init`)

Run:

```bash
agentmux init
```

In interactive mode, the wizard prompts for:

- `Default provider` from detected CLIs
- `Role setup` (use one provider for all roles, or customize per role)
- Per-role settings when customizing (`architect`, `product-manager`, `reviewer`, `coder`, `designer`)
- GitHub defaults:
  - `Base branch`
  - `Create draft PRs by default?`
  - `Branch prefix`
- `CLAUDE.md setup` (create from template, symlink an existing file, keep/skip)
- `Select prompt stubs to create`
- MCP research setup confirmation for supported providers

After init, the project contains:

- `.agentmux/config.yaml`
- Optional role prompt stubs in `.agentmux/prompts/agents/<role>.md`
- `CLAUDE.md` (created unless skipped or already present in defaults mode)

For non-interactive setup with built-in defaults:

```bash
agentmux init --defaults
```

For full init behavior details, see [Configuration](configuration.md) and [Prompts](prompts.md).

## First Pipeline Run

Start with a simple feature request:

```bash
agentmux "Add a health check endpoint"
```

What you will see:

- A tmux session with a monitor/control pane on the left and agent panes on the right
- Session name printed at launch (for example: `agentmux-<feature-name>`)
- Agents receiving prompt files and progressing by phase

To attach from another terminal:

```bash
tmux attach -t <session-name>
```

High-level phase flow:

1. Planning
2. Implementing
3. Reviewing
4. Completing

After review passes, AgentMux asks for approval (unless approval skipping is configured); you can approve or request changes before finalization:

- Commits changes locally
- Optionally opens a pull request if `gh` is available and configured

For phase-level details, see [File Protocol](file-protocol.md) and [Completing Phase](completing-phase.md).

## Tmux Essentials

If you are new to tmux, these commands are enough to observe runs:

- Attach to a running session:
  ```bash
  tmux attach -t <session>
  ```
- Detach without stopping agents: `Ctrl-b d`
- Move between panes: `Ctrl-b <arrow>`

Detaching does not stop the pipeline; agents keep running in the background.

## Troubleshooting

### tmux not installed

Common symptom: `agentmux` exits early because `tmux` is missing.

Install tmux, then retry:

```bash
# Debian/Ubuntu
sudo apt install tmux

# macOS (Homebrew)
brew install tmux
```

### CLI tool not authenticated

Common symptom: an agent pane hangs waiting for provider login, or the provider CLI returns an auth error.

Fix:

1. Run your provider CLI directly (for example `claude`) to complete authentication.
2. Confirm auth with `claude --version` / `codex --version` / `gemini --version` / `opencode --version`.
3. Re-run the pipeline.

## Next Steps

- Tune provider/profile settings in [Configuration](configuration.md)
- Add a requirements-refinement phase with `--product-manager`
- Bootstrap runs from GitHub issues with `--issue <number-or-url>`
- Continue interrupted work with `--resume` (see [Session Resumption](session-resumption.md))
- Use reference docs as needed:
  - [Tmux Layout](tmux-layout.md)
  - [Research Dispatch](research-dispatch.md)
  - [Monitor](monitor.md)
  - [Prompts](prompts.md)
