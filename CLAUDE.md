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
python3 pipeline.py "feature" --config <path>        # Custom config (default: pipeline_config.json)
python3 pipeline.py "feature" --keep-session         # Keep tmux session after completion

# Resume an interrupted pipeline
python3 pipeline.py --resume                         # Interactive selection from existing sessions
python3 pipeline.py --resume <feature-dir-or-name>  # Resume specific session by name or path
```

There are no test or lint commands — this is an MVP system without formal test infrastructure.

## Architecture

This is a **tmux-based multi-agent orchestration system**. Instead of calling AI APIs directly, it drives existing CLI tools (`claude`, `codex`, `gemini`, `opencode`) by injecting keystrokes into tmux panes. This reuses existing OAuth-authenticated subscriptions rather than pay-per-token API calls.

### How it works

`pipeline.py` is both the entry point and the orchestrator (started as a background subprocess with `--orchestrate`). It:
1. Creates a feature directory under `.multi-agent/<feature-name>/`
2. Spawns a tmux session with a **control pane** (left, 20 cols) and agent panes (right)
3. Watches the feature directory with `watchdog` for file changes
4. Advances the workflow state machine (`state.json`) based on which workflow artifacts appear/change
5. Injects the next prompt into the appropriate tmux pane

### State machine

The workflow progresses through these states (stored in `.multi-agent/<feature>/state.json`):

```
planning → designing? → implementing → reviewing
    → verdict:pass → documenting? → completing
    → verdict:fail → fixing → reviewing (review loop)
    → loop cap reached → completing
    → approval_received (done) OR changes_requested → planning
```

`state.json` persists the durable `phase` and optional metadata such as `last_event`, `review_iteration`, `subplan_count`, `research_tasks` (a dict tracking code-researcher task status by topic), and `web_research_tasks` (a dict tracking web-researcher task status by topic). Agents no longer write workflow statuses directly.

### Module structure

```
pipeline.py                    — entry point, CLI parsing, config loading, orchestrate() loop
src/models.py                  — AgentConfig (with trust_snippet) and RuntimeFiles dataclasses
src/providers.py               — Provider dataclass, PROVIDERS registry, resolve_agent() tier resolution
src/state.py                   — state.json CRUD, feature-directory lifecycle, parse_review_verdict
src/tmux.py                    — all tmux interaction (sessions, panes, send-keys, trust-prompt)
src/monitor.py                 — control pane status display (pipeline status, agent list, documents)
src/runtime.py                 — TmuxAgentRuntime, spawns agents with resolved trust_snippet
src/prompts.py                 — loads markdown templates and renders them with str.format_map()
src/prompts/agents/            — role-level prompts (define what each agent is)
  architect.md                 —   planning phase
  coder.md                     —   implementation phase
  code-researcher.md           —   codebase analysis on architect request
  web-researcher.md            —   internet search on architect request
src/prompts/commands/          — phase-specific command prompts (what to do at each step)
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
- `docs/configuration.md` — pipeline_config.json schema, provider abstraction, tier resolution
- `docs/tmux-layout.md` — Tmux session layout, pane lifecycle, zone approach
- `docs/research-dispatch.md` — Code-researcher and web-researcher task dispatch
- `docs/completing-phase.md` — Approval flow, commit selection, cleanup
- `docs/monitor.md` — Control pane display sections, constants, rendering
- `docs/prompts.md` — Prompt templates, placeholders, rendering pipeline
- `docs/session-resumption.md` — Resume flag, phase inference, runtime rehydration
