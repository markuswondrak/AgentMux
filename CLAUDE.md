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
```

There are no test or lint commands — this is an MVP system without formal test infrastructure.

## Architecture

This is a **tmux-based multi-agent orchestration system**. Instead of calling AI APIs directly, it drives existing CLI tools (`claude`, `codex`) by injecting keystrokes into tmux panes. This reuses existing OAuth-authenticated subscriptions rather than pay-per-token API calls.

### How it works

`pipeline.py` is both the entry point and the orchestrator (started as a background subprocess with `--orchestrate`). It:
1. Creates a feature directory under `.multi-agent/<feature-name>/`
2. Spawns a tmux session with agent panes
3. Watches the feature directory with `watchdog` for file changes
4. Advances the workflow state machine (`state.json`) based on which files appear/change
5. Injects the next prompt into the appropriate tmux pane

### State machine

The workflow progresses through these states (stored in `.multi-agent/<feature>/state.json`):

```
architect_requested → plan_ready → coder_requested → implementation_done
    → review_requested → review_ready
      → verdict:pass → completion_pending
      → verdict:fail → fix_requested → implementation_done (review loop)
      → loop cap reached → completion_pending
    → completion_approved (done) OR changes_requested → architect_requested (loop, review_iteration reset)
```

### Shared file protocol

Agents communicate via files in `.multi-agent/<feature-name>/`:
- `state.json` — current workflow state; orchestrator drives transitions
- `requirements.md` — initial request passed to architect
- `plan.md` — architect writes this; triggers coder spawn
- `review.md` — architect's code review; triggers confirmation phase
- `fix_request.md` — orchestrator-copied review findings for coder fix iterations
- `changes.md` — user feedback that triggers a re-plan cycle
- `context.md` — auto-generated rules/session info injected into prompts
- `*_prompt.txt` — rendered prompts that get injected into each agent's pane

### Agent configuration (`pipeline_config.json`)

Defines which CLI tools to use and their arguments for each role:
- **architect**: `claude --model opus` — plans, reviews, confirms
- **coder**: `codex` — implements the plan in the target project directory
- `max_review_iterations` caps automatic reviewer→coder fix loops before forcing user confirmation

The orchestrator never calls the AI APIs directly; it always goes through these CLI tools.

### Module structure

```
pipeline.py                    — entry point, CLI parsing, config loading, orchestrate() loop
src/models.py                  — AgentConfig and RuntimeFiles dataclasses
src/state.py                   — state.json CRUD, feature-directory lifecycle, parse_review_verdict
src/tmux.py                    — all tmux interaction (sessions, panes, send-keys, trust-prompt)
src/prompts.py                 — loads markdown templates and renders them with str.format_map()
src/prompts/agents/            — role-level prompts (define what each agent is)
  architect.md                 —   planning phase
  coder.md                     —   implementation phase
src/prompts/commands/          — phase-specific command prompts (what to do at each step)
  review.md                    —   code review
  fix.md                       —   fix review findings
  confirmation.md              —   user approval / changes gate
  change.md                    —   re-plan after user requests changes
```

### Key functions

- `orchestrate()` in `pipeline.py` — main file-watch loop; dispatches to role-specific handlers
- `send_prompt()` in `src/tmux.py` — injects text into a tmux pane via `send-keys`
- `build_*_prompt()` in `src/prompts.py` — loads and renders the markdown template for each phase
- `tmux_*` helpers in `src/tmux.py` — create/kill sessions, panes, capture output

### Editing prompts

Agent prompts live as plain markdown under `src/prompts/agents/` (role definitions) and
`src/prompts/commands/` (phase-specific instructions). Placeholders use `{name}` syntax
(rendered via `str.format_map`).

Every template receives `{feature_dir}` as the session directory and lists individual
filenames (e.g. `plan.md`, `state.json`) rather than full paths. The `change.md` template
additionally uses `<<<REQUIREMENTS_TEXT>>>`, `<<<PLAN_TEXT>>>`, and `<<<CHANGES_TEXT>>>`
markers that are substituted after format_map to safely embed arbitrary file content.

### Design constraints

- Agents never communicate with each other directly; the orchestrator mediates via files
- The orchestrator polls via watchdog events, not timers — no busy-waiting
- Human can attach to the tmux session at any time to observe or intervene
- Trust/confirmation prompts from CLI tools are automatically answered with Enter
