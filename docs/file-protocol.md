# Shared File Protocol

> Related source files: `agentmux/shared/models.py`, `agentmux/sessions/state_store.py`, `agentmux/runtime/event_bus.py`, `agentmux/runtime/file_events.py`, `agentmux/runtime/interruption_sources.py`, `agentmux/workflow/orchestrator.py`, `agentmux/workflow/phases.py`, `agentmux/workflow/handlers.py`, `agentmux/workflow/prompts.py`

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
- `plan.md` — human-readable planning overview
- `plan_<N>.md` — executable per-unit implementation plans referenced by scheduler metadata
- `execution_plan.json` — machine-readable schedule of ordered execution groups
  - Each group has a unique `group_id` and an execution mode (`serial` or `parallel`)
  - `serial` groups must reference exactly one named `plan_<N>.md` entry
  - `parallel` groups reference one or more named `plan_<N>.md` entries
  - Canonical plan-entry shape is `{ "file": "plan_<N>.md", "name": "Human title" }`
  - Plan references must be unique across groups
  - Group ordering defines implementation wave order
- `tasks.md` — architect implementation checklist derived from the same staged plan
- `plan_meta.json` — architect workflow-intent metadata:
  - `needs_design` (`true`/`false`) — whether to run a dedicated design handoff
  - `needs_docs` (`true`/`false`) — whether review-pass must enter docs before completion
  - `doc_files` (`string[]`) — expected docs update targets when `needs_docs` is `true`; must be `[]` when `needs_docs` is `false`

Compatibility behavior:

- Legacy flat plans without `execution_plan.json` still rely on `plan.md` `## Sub-plan <N>: ...` splitting into generated `plan_*.md` files.
- Legacy execution plans with `plans: ["plan_1.md"]` remain readable, but new architect output must use named plan objects.
- Staged execution should be preferred for new plans; legacy splitting is retained for backward compatibility.

## Research (`03_research/`)

- `code-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`
- `web-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`

## Design (`04_design/`)

- `designer_prompt.md` / `design.md`

## Implementation (`05_implementation/`)

- `coder_prompt.md` / `coder_prompt_*.txt`
- `done_*` — coder completion markers for implementing-phase scheduled plan units (`done_<N>` maps to `plan_<N>.md`)
- `done_1` — fixing-phase completion marker after a review-requested fix run
- `state.json` includes implementing-phase progress metadata so monitor/orchestrator can track:
  - `implementation_group_total` — total scheduled execution groups
  - `implementation_group_index` — current 1-based active group index (or total when implementation is complete)
  - `implementation_group_mode` — active group mode (`serial`/`parallel`)
  - `implementation_active_plan_ids` — active `plan_<N>` ids for the current group
  - `implementation_completed_group_ids` — ordered list of completed `group_id` values

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

- `PipelineOrchestrator.run()` / `build_event_bus()` in `agentmux/workflow/orchestrator.py` — run the phase loop on top of a shared session event bus
- `EventBus` in `agentmux/runtime/event_bus.py` — generic dispatcher plus start/stop lifecycle for dedicated event sources
- `FileEventSource` / `FeatureEventHandler` in `agentmux/runtime/file_events.py` — normalize watchdog activity under the feature directory and publish `file.*` events
- `CreatedFilesLogListener` / `seed_existing_files()` in `agentmux/runtime/file_events.py` — enforce created-file logging semantics (`created_files.log`, first-seen only, bootstrap coverage)
- `InterruptionEventSource` in `agentmux/runtime/interruption_sources.py` — publish interruption events when registered tmux panes disappear
- `build_initial_prompts()` in `agentmux/workflow/prompts.py` — builds only the architect prompt at startup
- `build_*_prompt()` in `agentmux/workflow/prompts.py` — loads and renders the markdown template for each phase; called lazily by handlers
- Handler functions in `agentmux/workflow/handlers.py` — each builds and writes its prompt file just before sending to agent
