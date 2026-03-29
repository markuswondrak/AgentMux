# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

```bash
# Install dependencies
python3 -m pip install -r requirements.txt

# Initialize a new project (scaffolds configuration)
agentmux init                                        # Interactive setup wizard
agentmux init --defaults                             # Non-interactive with built-in defaults

# Start a feature workflow
agentmux "Your feature description"

# Optional flags
agentmux "feature" --name <slug>                     # Custom feature directory name
agentmux "feature" --config <path>                   # Explicit config override
agentmux "feature" --keep-session                    # Keep tmux session after completion
agentmux "feature" --product-manager                 # Run PM phase before architect planning

# Bootstrap from GitHub issue
agentmux issue <number-or-url>                       # Bootstrap from GitHub issue title/body
agentmux issue <number-or-url> --name <slug>         # Custom feature directory name
agentmux issue <number-or-url> --product-manager     # Run PM phase before architect planning

# Resume an interrupted pipeline
agentmux resume                                      # Interactive selection from existing sessions
agentmux resume <feature-dir-or-name>                # Resume specific session by name or path
agentmux resume <session> --keep-session             # Keep tmux session after completion

# Session management commands
agentmux sessions                                    # List all sessions with phase, status, and timestamp
agentmux clean                                       # Remove all sessions (prompts for confirmation)
agentmux clean --force                               # Remove all sessions without confirmation

# Shell tab completion
agentmux completions bash                            # Print bash completion script
agentmux completions zsh                             # Print zsh completion script
# Enable with: eval "$(agentmux completions bash)" in your .bashrc
```

### Project Initialization

The `agentmux init` command scaffolds a new project with configuration, setup files, and optional custom prompts:

- **Detects installed CLI tools** — Checks for `claude`, `codex`, `gemini`, `opencode` and displays availability
- **Interactive role configuration** — Offers a quick path that uses the selected default provider across roles, or a custom per-role setup path
- **MCP setup** — Prompts to install the `agentmux-research` MCP server at the provider's native config scope for the effective architect/product-manager providers when missing
- **GitHub settings** — Configures base branch, draft PR preferences, branch prefix
- **CLAUDE.md setup** — Creates from template, symlinks existing file, or skips
- **Prompt stubs** — Generates optional project-specific instructions in `.agentmux/prompts/agents/<role>.md`
- **Config validation** — Verifies the generated `.agentmux/config.yaml` parses correctly

Test command:
- `python -m pytest tests`

There are no lint commands in this repository.

Default config resolution is layered:
- built-in defaults from `agentmux/configuration/defaults/config.yaml`
- optional user config from `~/.config/agentmux/config.yaml`
- project config from `.agentmux/config.yaml`
- explicit `--config <path>` override

## Architecture

This is a **tmux-based multi-agent orchestration system**. Instead of calling AI APIs directly, it drives existing CLI tools (`claude`, `codex`, `gemini`, `opencode`) by injecting keystrokes into tmux panes. This reuses existing OAuth-authenticated subscriptions rather than pay-per-token API calls.

### How it works

The pipeline application:
1. Creates a feature directory under `.agentmux/.sessions/<feature-name>/`
2. Spawns a tmux session with a **control pane** (left, 15 cols) and agent panes (right)
   - Pane border titles are enabled so each pane shows its role name
3. Starts a session file monitor that watches the feature directory with `watchdog` and normalizes file activity to feature-relative paths
4. Fans those file events out to listeners that wake the orchestration loop and append first-seen file creations to `created_files.log` (including startup files via one-time seeding)
5. Advances the workflow state machine (`state.json`) based on which workflow artifacts appear/change
6. Injects the next prompt into the appropriate tmux pane

### State machine

The workflow progresses through these states (stored in `.agentmux/.sessions/<feature>/state.json`):

``` 
product_management? → planning → designing? → implementing → reviewing
    → verdict:pass → completing
    → verdict:fail → fixing → reviewing (review loop)
    → loop cap reached → completing
    → approval_received (done) OR changes_requested → planning
```

Role routing in these phases:
- `product-manager`: product management phase only
- `architect`: planning/replanning only
- `reviewer`: reviewing and final confirmation/completion prompts
- `coder`: implementing/fixing

`state.json` persists the durable `phase` and optional metadata such as `last_event`, `review_iteration`, `subplan_count`, `product_manager`, `research_tasks` (a dict tracking code-researcher task status by topic), `web_research_tasks` (a dict tracking web-researcher task status by topic), and GitHub integration keys like `gh_available` / `issue_number`. Agents no longer write workflow statuses directly.

### Component structure

```
agentmux/pipeline/__init__.py       — CLI parsing and `main()`
agentmux/pipeline/application.py    — PipelineApplication, launcher flow, hidden `--orchestrate` mode
agentmux/pipeline/init_command.py   — project initialization wizard

agentmux/configuration/             — layered config loading, provider/profile resolution, built-in defaults
agentmux/configuration/providers.py — built-in provider helpers for launcher/profile resolution

agentmux/shared/models.py           — AgentConfig, GitHubConfig, RuntimeFiles
agentmux/sessions/__init__.py       — SessionService, session creation/resume
agentmux/sessions/state_store.py    — state.json CRUD, feature-directory lifecycle, commit/cleanup helpers

agentmux/runtime/__init__.py        — TmuxAgentRuntime and TmuxRuntimeFactory
agentmux/runtime/tmux_control.py    — tmux control, pane/session lifecycle, prompt dispatch
agentmux/runtime/event_bus.py       — shared session event bus
agentmux/runtime/file_events.py     — watchdog integration and created-files logging
agentmux/runtime/interruption_sources.py — missing-pane interruption source

agentmux/workflow/orchestrator.py   — orchestration loop on top of runtime event sources
agentmux/workflow/phases.py         — workflow phase state machine
agentmux/workflow/prompts.py        — prompt rendering and prompt-file creation
agentmux/workflow/handlers.py       — phase helpers and state writes
agentmux/workflow/transitions.py    — PipelineContext and transition helpers
agentmux/workflow/interruptions.py  — interruption catalog and reporting
agentmux/workflow/plan_parser.py    — execution-plan-backed subplan labels

agentmux/monitor/__init__.py        — monitor command entrypoint
agentmux/monitor/state_reader.py    — monitor state/log aggregation
agentmux/monitor/render.py          — ANSI rendering for the control pane
agentmux/terminal_ui/console.py     — interactive terminal session selection
agentmux/terminal_ui/screens.py     — welcome/goodbye terminal screens and shared logo
agentmux/terminal_ui/layout.py      — shared terminal layout constants

agentmux/integrations/github.py     — GitHub issue bootstrap and PR creation
agentmux/integrations/mcp.py        — provider-native MCP setup plus runtime env wiring
agentmux/integrations/mcp_research_server.py — shared MCP research server
agentmux/integrations/completion.py — completion-time commit / PR / cleanup side effects
agentmux/integrations/compression.py — headroom proxy lifecycle and agent env injection

agentmux/prompts/agents/            — role-level prompts (define what each agent is)
  product-manager.md           —   product management phase
  architect.md                 —   planning phase
  reviewer.md                  —   review + confirmation phases
  coder.md                     —   implementation phase
  code-researcher.md           —   codebase analysis on architect request
  web-researcher.md            —   internet search on architect request
agentmux/prompts/commands/          — phase-specific command prompts (what to do at each step)
  review.md                    —   code review
  fix.md                       —   fix review findings
  confirmation.md              —   user approval / changes gate
  change.md                    —   re-plan after user requests changes
```

### Design constraints

- Agents never communicate with each other directly; the orchestrator mediates via files
- The orchestrator polls via watchdog events, not timers — no busy-waiting
- Files are created on-demand for workflow phases, and the orchestrator also maintains a root-level `created_files.log` runtime artifact that records first-seen created files once per relative path
- Prompt files are built lazily by handlers just before injection, not pre-generated
- Human can attach to the tmux session at any time to observe or intervene
- Trust/confirmation prompts from CLI tools are automatically answered with Enter
- Workflow code should depend on runtime/session abstractions, not directly on tmux or GitHub helpers

## Documentation Maintenance

When you modify code that changes behavior documented in `docs/`, update the relevant doc file in the same change. Each doc file lists its related source files at the top — use this to determine which docs are affected.

Rules:
- **New workflow file or phase**: Update `docs/file-protocol.md`
- **Config schema or provider change**: Update `docs/configuration.md`
- **Tmux pane logic**: Update `docs/tmux-layout.md`
- **Research dispatch**: Update `docs/research-dispatch.md`
- **Completion/commit flow**: Update `docs/completing-phase.md`
- **Monitor constants or sections**: Update `docs/monitor.md`
- **Prompt templates or rendering**: Update `docs/prompts.md`
- **Resume logic**: Update `docs/session-resumption.md`
- **Architectural changes** (new phases, new agents, state machine transitions): Update this file (CLAUDE.md)
- Do **not** document implementation details that are obvious from reading the code — docs describe contracts, flows, and schemas

## Detailed Documentation

Deeper context on specific subsystems:

- `docs/file-protocol.md` — Shared file protocol, workflow artifacts per phase
- `docs/configuration.md` — layered config schema, launchers/profiles
- `docs/tmux-layout.md` — Tmux session layout, pane lifecycle, zone approach
- `docs/research-dispatch.md` — Code-researcher and web-researcher task dispatch
- `docs/completing-phase.md` — Approval flow, commit selection, cleanup
- `docs/monitor.md` — Control pane display sections, constants, rendering
- `docs/prompts.md` — Prompt templates, placeholders, rendering pipeline, and coder research handoff injection
- `docs/session-resumption.md` — Resume flag, phase inference, runtime rehydration
