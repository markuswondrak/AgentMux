# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Pipeline

```bash
# Install dependencies
python3 -m pip install -r requirements.txt

# Start a feature workflow
python3 pipeline.py "Your feature description"

# Optional flags
python3 pipeline.py "feature" --name <slug>          # Custom feature directory name
python3 pipeline.py "feature" --config <path>        # Explicit config override
python3 pipeline.py "feature" --keep-session         # Keep tmux session after completion
python3 pipeline.py "feature" --product-manager      # Run PM phase before architect planning
python3 pipeline.py --issue <number-or-url>          # Bootstrap from GitHub issue title/body

# Resume an interrupted pipeline
python3 pipeline.py --resume                         # Interactive selection from existing sessions
python3 pipeline.py --resume <feature-dir-or-name>  # Resume specific session by name or path
```

There are no test or lint commands — this is an MVP system without formal test infrastructure.

Default config resolution is layered:
- built-in defaults from `agentmux/defaults/config.yaml`
- optional user config from `~/.config/agentmux/config.yaml`
- project config from `.agentmux/config.yaml` (preferred) or legacy `pipeline_config.json`
- explicit `--config <path>` override

## Architecture

This is a **tmux-based multi-agent orchestration system**. Instead of calling AI APIs directly, it drives existing CLI tools (`claude`, `codex`, `gemini`, `opencode`) by injecting keystrokes into tmux panes. This reuses existing OAuth-authenticated subscriptions rather than pay-per-token API calls.

### How it works

`agentmux/pipeline.py` is the orchestrator implementation (started as a background subprocess with `--orchestrate`).
The repo-root `pipeline.py` is a backward-compatible shim that calls `agentmux.pipeline:main`.
The orchestrator:
1. Creates a feature directory under `.multi-agent/<feature-name>/`
2. Spawns a tmux session with a **control pane** (left, 15 cols) and agent panes (right)
   - Pane border titles are enabled so each pane shows its role name
3. Watches the feature directory with `watchdog` for file changes
4. Advances the workflow state machine (`state.json`) based on which workflow artifacts appear/change
5. Injects the next prompt into the appropriate tmux pane

### State machine

The workflow progresses through these states (stored in `.multi-agent/<feature>/state.json`):

```
product_management? → planning → designing? → implementing → reviewing
    → verdict:pass → documenting? → completing
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

### Module structure

```
pipeline.py                    — backward-compatible CLI shim (`agentmux.pipeline:main`)
agentmux/pipeline.py           — CLI parsing, config loading, orchestrate() loop
agentmux/config.py                  — layered config loading, legacy compatibility, role resolution
agentmux/models.py                  — AgentConfig (with trust_snippet/model_flag) and RuntimeFiles dataclasses
agentmux/providers.py               — built-in provider compatibility helpers for profiles/models
agentmux/state.py                   — state.json CRUD, feature-directory lifecycle, parse_review_verdict
agentmux/tmux.py                    — all tmux interaction (sessions, panes, send-keys, trust-prompt)
agentmux/monitor.py                 — control pane status display (pipeline status, agent list, documents)
agentmux/runtime.py                 — TmuxAgentRuntime, spawns agents with resolved trust_snippet
agentmux/prompts.py                 — loads markdown templates and renders them with str.format_map()
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
- Files are created on-demand — only essential files (`state.json`, `requirements.md`, `context.md`) exist at startup; all others are created when the corresponding workflow step fires
- Prompt files are built lazily by handlers just before injection, not pre-generated
- Human can attach to the tmux session at any time to observe or intervene
- Trust/confirmation prompts from CLI tools are automatically answered with Enter

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
- `docs/configuration.md` — layered config schema, launchers/profiles, legacy compatibility
- `docs/tmux-layout.md` — Tmux session layout, pane lifecycle, zone approach
- `docs/research-dispatch.md` — Code-researcher and web-researcher task dispatch
- `docs/completing-phase.md` — Approval flow, commit selection, cleanup
- `docs/monitor.md` — Control pane display sections, constants, rendering
- `docs/prompts.md` — Prompt templates, placeholders, rendering pipeline
- `docs/session-resumption.md` — Resume flag, phase inference, runtime rehydration
