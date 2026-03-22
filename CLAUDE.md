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

The tmux layout uses a "zone" approach: the **monitor zone** (left, fixed 20 cols) and the **agent zone** (right, remaining space). The control pane width is set once at session creation via `resize-pane -x 20` and never touched programmatically again. Agents are swapped into the right zone via `swap-pane` (exclusive) or stacked with `join-pane -v` (parallel). Idle agents are parked in a hidden `_hidden` window via `break-pane -d`. None of these operations affect the horizontal partition, so the monitor width stays rock-solid.

### Session resumption

When a pipeline is interrupted (e.g., connection loss, tmux session killed), it can be restarted from where it left off using `--resume`:

- `list_resumable_sessions(project_dir)` scans `.multi-agent/` for all feature directories with `state.json` and returns them sorted by recency
- `select_session(sessions)` presents an interactive menu (or auto-selects if only one exists)
- `infer_resume_phase(feature_dir, state)` examines workflow artifacts (`plan.md`, `done_*`, `review.md`, etc.) to determine the correct phase to resume into
- On resume, the phase is updated in `state.json`, `last_event` is set to `"resumed"`, and any research tasks with `"dispatched"` status are cleaned up (allowing re-request)
- The orchestrator picks up the updated state and injects the appropriate phase prompt to resume work

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

### Shared file protocol

Agents communicate via files in `.multi-agent/<feature-name>/`. Files are created on-demand as needed, not all at startup:

**Created at initialization:**
- `state.json` — current workflow phase; orchestrator drives transitions
- `requirements.md` — initial request passed to architect
- `context.md` — auto-generated rules/session info injected into prompts
- `panes.json` — tmux pane IDs written by `main()`, read by the background orchestrator
- `architect_prompt.txt` — initial prompt for architect

**Created on-demand during workflow:**
- `plan.md` / `tasks.md` / `plan_meta.json` — architect planning artifacts
- `research_request_<topic>.md` — architect's research assignment to code-researcher
- `research_summary_<topic>.md` — code-researcher's high-level answers for architect
- `research_detail_<topic>.md` — code-researcher's detailed analysis for coder/designer
- `research_done_<topic>` — code-researcher completion marker (empty file)
- `web_research_request_<topic>.md` — architect's research assignment to web-researcher
- `web_research_summary_<topic>.md` — web-researcher's high-level answers for architect
- `web_research_detail_<topic>.md` — web-researcher's detailed findings for coder/designer
- `web_research_done_<topic>` — web-researcher completion marker (empty file)
- `coder_prompt*.txt` — built and injected when implementation starts
- `designer_prompt.md` — built and injected when designing starts
- `review.md` / `review_prompt.md` — architect review result and prompt
- `fix_request.md` / `fix_prompt.txt` — fix-loop handoff and prompt
- `done_*` — coder completion markers for single or parallel implementation/fixing
- `docs_prompt.txt` / `docs_done` — docs prompt and completion marker
- `confirmation_prompt.md` / `approval.json` — completion prompt and approval payload
- `changes.md` / `changes_prompt.txt` — change request feedback and replanning prompt

### Agent configuration (`pipeline_config.json`)

Configuration specifies providers and tier levels (rather than explicit CLI tools and models), allowing roles to use different AI backends and capability levels:

```json
{
  "session_name": "multi-agent-mvp",
  "provider": "claude",
  "max_review_iterations": 3,
  "architect": { "tier": "max" },
  "coder": { "provider": "codex", "tier": "standard" },
  "designer": { "tier": "standard" },
  "docs": { "tier": "low" },
  "code-researcher": { "tier": "low" },
  "web-researcher": { "tier": "standard" }
}
```

**Configuration keys:**
- `provider` (top-level): default provider for all roles — defaults to `"claude"`; supported providers are `"claude"`, `"codex"`, `"gemini"`, `"opencode"`
- Per-role `provider` (optional): overrides the global provider for that role
- `tier` (per role): `"max"` / `"standard"` / `"low"` — resolved to a concrete model by the provider
- `args` (per role, optional): overrides the provider's default CLI arguments for that role
- `max_review_iterations` caps automatic reviewer→coder fix loops before forcing user confirmation

**Tier-to-model mapping:**
| Tier | claude | codex | gemini | opencode |
|------|--------|-------|--------|----------|
| max | `opus` | `gpt-5.4-codex-medium` | `gemini-2.5-pro` | `anthropic/claude-opus-4-6` |
| standard | `sonnet` | `gpt-5.3-codex-high` | `gemini-2.5-flash` | `anthropic/claude-sonnet-4-20250514` |
| low | `haiku` | `gpt-5.2-codex` | `gemini-2.5-flash-lite` | `anthropic/claude-haiku-4-5-20251001` |

The orchestrator never calls the AI APIs directly; it always goes through these CLI tools, looking up the appropriate model via provider configuration.

### Monitor display (src/monitor.py)

The control pane renders a live status box with the following sections:

- **Feature request** — the initial feature description from `requirements.md`
- **Pipeline stages** — progress through the workflow (planning, implementing, reviewing, completing, done)
  - Always-visible stages: `planning`, `implementing`, `reviewing`, `completing`
  - Optional phases (shown only when active): `designing`, `fixing`, `documenting`
  - Displayed with `▶` for active, `·` for inactive
- **Pipeline metadata** — human-readable event label (e.g. "plan ready" for `plan_written`), review iteration count, subplan count
- **Agents** — list of all agents with their status (●WORKING / ●IDLE / ○inactive) and provider/model info
- **Research tasks** — progress on code and web research (if any)
- **Documents** — workflow output files present: `plan.md`, `tasks.md`, `design.md`, `review.md`, `changes.md` (shown with ✓ when present)
- **Event log** — recent phase transitions with timestamps

Key constants in the monitor:
- `ALWAYS_VISIBLE_STATES` — phases shown in all cases
- `OPTIONAL_PHASES` — phases hidden until they are the active phase
- `EVENT_LABELS` — mapping of internal event names (e.g. `plan_written`) to user-friendly labels (e.g. "plan ready")
- `DOCUMENT_FILES` — list of workflow output files to track

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

### Key functions

- `orchestrate()` in `pipeline.py` — main file-watch loop; dispatches to role-specific handlers
- `send_prompt()` in `src/tmux.py` — injects text into a tmux pane via `send-keys`
- `build_initial_prompts()` in `src/prompts.py` — builds only the architect prompt at startup
- `build_*_prompt()` in `src/prompts.py` — loads and renders the markdown template for each phase; called lazily by handlers
- Handler functions in `src/handlers.py` — each builds and writes its prompt file just before sending to agent
- `tmux_*` helpers in `src/tmux.py` — create/kill sessions, panes, capture output
- `_fix_control_width()` in `src/tmux.py` — one-shot resize fallback, only used when the right zone was empty
- `list_resumable_sessions()` in `pipeline.py` — scans `.multi-agent/` for all feature directories with `state.json`, sorted by recency
- `select_session()` in `pipeline.py` — presents interactive menu for user to select a session, or auto-selects if only one exists
- `infer_resume_phase()` in `src/state.py` — examines workflow artifacts to determine the correct phase to resume into, cleans up dispatched research tasks

### Code-researcher task dispatch

During the planning phase, the architect can request deep codebase analysis by writing `research_request_<topic>.md` files (where `<topic>` is a descriptive slug like `auth-module` or `db-schema`). The orchestrator:

1. Detects the new request file
2. Spawns a code-researcher pane (parallel to architect, not exclusive)
3. Injects the research assignment and tracks the topic in `state.json["research_tasks"]`
4. Code-researcher analyzes the codebase and produces:
   - `research_summary_<topic>.md` — concise answers for architect
   - `research_detail_<topic>.md` — comprehensive analysis for coder/designer
   - `research_done_<topic>` — empty completion marker
5. Orchestrator notifies architect when analysis is complete

Multiple research tasks can run in parallel. The architect can continue planning while research is underway and incorporate findings when ready.

### Web-researcher task dispatch

During the planning phase, the architect can request internet research by writing `web_research_request_<topic>.md` files (where `<topic>` is a descriptive slug like `nodejs-versions` or `aws-pricing`). The orchestrator:

1. Detects the new request file
2. Spawns a web-researcher pane (parallel to architect, not exclusive)
3. Injects the research assignment and tracks the topic in `state.json["web_research_tasks"]`
4. Web-researcher searches the internet via WebFetch and WebSearch tools and produces:
   - `web_research_summary_<topic>.md` — concise answers with version numbers and source URLs for architect
   - `web_research_detail_<topic>.md` — comprehensive findings with full citations for coder/designer
   - `web_research_done_<topic>` — empty completion marker
5. Orchestrator notifies architect when analysis is complete

Multiple web research tasks can run in parallel and simultaneously with code-researcher tasks. The architect can continue planning while research is underway and incorporate findings when ready. Web-researcher is configured to use Sonnet (not Haiku) for better reasoning about sources and precision regarding version numbers and technical specifications.

### Completing phase

When the review passes, the workflow enters the `documenting` phase (if docs updates are needed) and then transitions to `completing`. In the completing phase:

1. **Confirmation prompt displays changed files** — The confirmation prompt shows all files detected by `git status --porcelain` from the project directory. This gives the architect full visibility into what will be committed.

2. **Architect specifies exclusions (not inclusions)** — Instead of manually enumerating files to commit, the architect simply lists any files to **exclude** from the commit in the `approval.json` response. By default, an empty `exclude_files` list means commit all detected changes.

3. **`approval.json` schema**:
   ```json
   {
     "action": "approve",
     "commit_message": "...",
     "exclude_files": []
   }
   ```

4. **Auto-detection and filtering** — The completing phase handler (`CompletingPhase.handle_event()`) reads git status again when processing the approval, removes any files listed in `exclude_files`, and passes the remaining file list to `commit_changes()`.

5. **Cleanup only on success** — The feature directory is deleted only if the commit succeeds (commit hash is not `None`). If the commit fails, the feature directory is preserved so the user can investigate and retry.

This flow ensures the architect always knows what's being committed and can selectively exclude unrelated changes without losing the ability to retry after a failed commit.

### Provider abstraction

The `src/providers.py` module defines how different AI CLI tools (providers) are configured:

**Provider dataclass:**
- `name` — identifier (`"claude"`, `"codex"`, `"gemini"`, `"opencode"`)
- `cli` — binary name (e.g., `"claude"`, `"codex"`)
- `models` — dict mapping tier (`"max"`, `"standard"`, `"low"`) to model name
- `trust_snippet` — text to detect for auto-accept (e.g., `"Do you trust the contents of this directory?"`), or `None` if no trust prompt
- `default_args` — dict mapping role name to default CLI argument list

**Tier resolution:**
The `resolve_agent(global_provider, role, role_config)` function:
1. Determines effective provider: uses `role_config.get("provider")` if specified, otherwise falls back to global `provider`
2. Looks up the `Provider` from the `PROVIDERS` registry
3. Resolves the `tier` to a concrete model name via `provider.models[tier]`
4. Resolves CLI args: uses `role_config.get("args")` if present, otherwise `provider.default_args.get(role, [])`
5. Returns an `AgentConfig` with the resolved cli, model, args, and trust_snippet

This allows configuration changes (switching providers, adjusting tiers) without modifying agent implementation code.

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
- Files are created on-demand — only essential files (`state.json`, `requirements.md`, `context.md`) exist at startup; all others are created when the corresponding workflow step fires
- Prompt files are built lazily by handlers just before injection, not pre-generated
- Human can attach to the tmux session at any time to observe or intervene
- Trust/confirmation prompts from CLI tools are automatically answered with Enter
