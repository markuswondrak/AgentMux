# Shared File Protocol

> Related source files: `agentmux/models.py`, `agentmux/state.py`, `agentmux/event_bus.py`, `agentmux/session_events.py`, `agentmux/interruption_sources.py`, `agentmux/pipeline.py`, `agentmux/phases.py`, `agentmux/handlers.py`

Agents communicate via files in `.agentmux/.sessions/<feature-name>/`. Files are grouped by phase subdirectories and created on-demand as needed, while a small set of root runtime artifacts is maintained directly by the orchestrator.

## Root files

- `state.json` — current workflow phase; orchestrator drives transitions
- `requirements.md` — initial request passed to architect
- `context.md` — auto-generated rules/session info injected into prompts
- `runtime_state.json` / `orchestrator.log` — runtime tracking and orchestrator logs
- `created_files.log` — append-only created-file history written by the orchestrator as `YYYY-MM-DD HH:MM:SS  relative/path`; records files only (not directories), deduplicated by relative path, and seeded once at startup to include pre-existing session files

## Product Management (`01_product_management/`)

- `product_manager_prompt.md` — prompt for PM analysis phase
- `analysis.md` — PM write-up (business case, integration assessment, alternatives)
- `done` — completion marker for PM handoff to planning

## Planning (`02_planning/`)

- `architect_prompt.md` / `changes_prompt.txt` — architect prompts
- `plan.md` / `tasks.md` — architect planning artifacts
- `plan_meta.json` — architect workflow-intent metadata:
  - `needs_design` (`true`/`false`) — whether to run a dedicated design handoff
  - `needs_docs` (`true`/`false`) — whether review-pass must enter docs before completion
  - `doc_files` (`string[]`) — expected docs update targets when `needs_docs` is `true`; must be `[]` when `needs_docs` is `false`
- `plan_*.md` — subplan files for parallel coder runs

## Research (`03_research/`)

- `code-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`
- `web-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`

## Design (`04_design/`)

- `designer_prompt.md` / `design.md`

## Implementation (`05_implementation/`)

- `coder_prompt.md` / `coder_prompt_*.txt`
- `done_*` — coder completion markers for single or parallel implementation/fixing runs

## Review (`06_review/`)

- `review_prompt.md` / `review.md`
- `fix_prompt.txt` / `fix_request.md`

## Docs (`07_docs/`)

- `docs_prompt.txt` / `docs_done`
- `docs_prompt.txt` must be scoped by `02_planning/plan_meta.json` `doc_files`; no implicit `README.md`/`CLAUDE.md` targets are added

## Completion (`08_completion/`)

- `confirmation_prompt.md` / `approval.json`
- `changes.md`

## Key functions

- `orchestrate()` / `build_orchestrator_event_bus()` in `agentmux/pipeline.py` — run the phase loop on top of a shared session event bus
- `EventBus` in `agentmux/event_bus.py` — generic dispatcher plus start/stop lifecycle for dedicated event sources
- `FileEventSource` / `FeatureEventHandler` in `agentmux/session_events.py` — normalize watchdog activity under the feature directory and publish `file.*` events
- `CreatedFilesLogListener` / `seed_existing_files()` in `agentmux/session_events.py` — enforce created-file logging semantics (`created_files.log`, first-seen only, bootstrap coverage)
- `InterruptionEventSource` in `agentmux/interruption_sources.py` — publish interruption events when registered tmux panes disappear
- `build_initial_prompts()` in `agentmux/prompts.py` — builds only the architect prompt at startup
- `build_*_prompt()` in `agentmux/prompts.py` — loads and renders the markdown template for each phase; called lazily by handlers
- Handler functions in `agentmux/handlers.py` — each builds and writes its prompt file just before sending to agent
