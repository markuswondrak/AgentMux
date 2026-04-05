# Shared File Protocol

> Related source files: `agentmux/shared/models.py`, `agentmux/sessions/state_store.py`, `agentmux/runtime/event_bus.py`, `agentmux/runtime/file_events.py`, `agentmux/runtime/interruption_sources.py`, `agentmux/workflow/orchestrator.py`, `agentmux/workflow/event_router.py`, `agentmux/workflow/phases.py`, `agentmux/workflow/handlers.py`, `agentmux/workflow/prompts.py`

Agents communicate via files in `.agentmux/.sessions/<feature-name>/`. Files are grouped by phase subdirectories and created on-demand as needed, while a small set of root runtime artifacts is maintained directly by the orchestrator.

## Root files

- `state.json` — current workflow phase; orchestrator drives transitions
- `requirements.md` — initial request passed to architect
- `context.md` — auto-generated rules/session info injected into prompts
- `runtime_state.json` / `orchestrator.log` — runtime tracking and orchestrator logs
- `created_files.log` — append-only created-file history written by the orchestrator as `YYYY-MM-DD HH:MM:SS  relative/path`; records files only (not directories), deduplicated by relative path, and seeded once at startup to include pre-existing session files

## Product Management (`01_product_management/`)

- `product_manager_prompt.md` — prompt for PM analysis phase
- `analysis.md` — PM usability rationale: friction points, integration fit, alternatives considered and rejected, notes for the architect. Advisory only — if it conflicts with `requirements.md`, `requirements.md` wins.
- `done` — completion marker for PM handoff to planning

## Planning (`02_planning/`)

- `architect_prompt.md` / `changes_prompt.txt` — architect prompts (for architecting phase)
- `planner_prompt.md` — planner prompt for creating execution plans
- `architecture.md` — technical architecture document created by architect (the "What" and "With what")
- `plan.md` — human-readable planning overview created by planner
- `plan_<N>.md` — executable per-unit implementation plans referenced by scheduler metadata
- `execution_plan.json` — machine-readable schedule of ordered execution groups
  - Each group has a unique `group_id` and an execution mode (`serial` or `parallel`)
  - `serial` groups execute plans one at a time in order (useful for sequential integration steps)
  - `parallel` groups execute all plans simultaneously
  - Both modes can reference one or more named `plan_<N>.md` entries
  - Canonical plan-entry shape is `{ "file": "plan_<N>.md", "name": "Human title" }`
  - Plan references must be unique across groups
  - Group ordering defines implementation wave order
- `tasks_<N>.md` — per-plan implementation checklists; each coder receives only their assigned plan's tasks
- `tasks.md` — optional human-readable overview summarizing all tasks (not used by scheduler)
- `plan_meta.json` — planner workflow-intent metadata:
  - `needs_design` (`true`/`false`) — whether to run a dedicated design handoff
  - `needs_docs` (`true`/`false`) — informational signal that documentation updates are in scope
  - `doc_files` (`string[]`) — planned documentation targets when docs work is in scope
  - `review_strategy` (`object`) — risk assessment and review scope configuration:
    - `severity` (`"low"`|`"medium"`|`"high"`) — implementation risk level: `low` for UI/CSS/text, `medium` for logic changes, `high` for security/DB/core changes
    - `focus` (`string[]`) — specific review focus areas (e.g., `["security", "performance", "data-consistency"]`)
  - Documentation updates must be captured explicitly in `plan.md`, each `plan_<N>.md`, and corresponding `tasks_<N>.md`; this metadata does not create a separate runtime phase

Execution scheduling is strict:

- `execution_plan.json` is required before implementation starts.
- `groups[].plans[]` entries must use `{ "file": "plan_<N>.md", "name": "Human title" }` objects.
- Implementation dispatch uses numbered prompt files (`coder_prompt_<N>.txt`) only.

## Research (`03_research/`)

- `code-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`
- `web-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`

## Design (`04_design/`)

- `designer_prompt.md` / `design.md`

## Implementation (`05_implementation/`)

- `coder_prompt_<N>.txt` — implementing-phase prompts mapped to scheduled plan units (`plan_<N>.md`)
- `done_*` — coder completion markers for implementing-phase scheduled plan units (`done_<N>` maps to `plan_<N>.md`)
- `done_1` — fixing-phase completion marker after a review-requested fix run
- `state.json` includes implementing-phase progress metadata so monitor/orchestrator can track:
  - `implementation_group_total` — total scheduled execution groups
  - `implementation_group_index` — current 1-based active group index (or total when implementation is complete)
  - `implementation_group_mode` — active group mode (`serial`/`parallel`)
  - `implementation_active_plan_ids` — active `plan_<N>` ids for the current group
  - `implementation_completed_group_ids` — ordered list of completed `group_id` values

## Review (`06_review/`)

- `review_prompt.md` / `review.md` — legacy review prompt (backward compatibility)
- `review_logic_prompt.md` — Logic & Alignment reviewer prompt (functional correctness vs plan)
- `review_quality_prompt.md` — Quality & Style reviewer prompt (clean code, naming, standards)
- `review_expert_prompt.md` — Deep-Dive Expert reviewer prompt (security, performance, edge cases)
- `fix_prompt.txt` / `fix_request.md`

**Reviewer Selection:** Which prompt is used depends on `plan_meta.review_strategy`:
- Missing `review_strategy` → uses `review_logic_prompt.md` (backward compatible default)
- `severity: low` → uses `review_quality_prompt.md`
- `severity: medium/high` without security/performance focus → uses `review_logic_prompt.md`
- `severity: medium/high` with security or performance in focus → uses `review_expert_prompt.md`

## Completion (`08_completion/`)

- `summary_prompt.md` — prompt asking reviewer to write an implementation summary
- `summary.md` — reviewer-written implementation summary (what was done, key decisions)
- `approval.json` — written by the native completion UI when user approves
- `changes.md` — written by the native completion UI when user requests changes

## Key functions

- `PipelineOrchestrator.run()` / `build_event_bus()` in `agentmux/workflow/orchestrator.py` — run the phase loop on top of a shared session event bus
- `EventBus` in `agentmux/runtime/event_bus.py` — generic dispatcher plus start/stop lifecycle for dedicated event sources
- `FileEventSource` / `FeatureEventHandler` in `agentmux/runtime/file_events.py` — normalize watchdog activity under the feature directory and publish `file.*` events
- `CreatedFilesLogListener` / `seed_existing_files()` in `agentmux/runtime/file_events.py` — enforce created-file logging semantics (`created_files.log`, first-seen only, bootstrap coverage)
- `InterruptionEventSource` in `agentmux/runtime/interruption_sources.py` — publish interruption events when registered tmux panes disappear
- `WorkflowEventRouter.enter_current_phase()` in `agentmux/workflow/event_router.py` — explicitly bootstraps the active phase before steady-state event processing starts
- `build_*_prompt()` in `agentmux/workflow/prompts.py` — loads and renders the markdown template for each phase; called lazily by handlers
- Handler functions in `agentmux/workflow/handlers.py` — each builds and writes its prompt file just before sending to agent

## Workflow Events

`state.json` contains a `last_event` field that records the most recent workflow event driving the current phase. The authoritative catalog of valid values and display metadata is in `src/agentmux/workflow/event_catalog.py`. Phase-to-event emission wiring lives in `src/agentmux/workflow/phase_registry.py` via `PhaseDescriptor.emitted_events`. Unknown values are rejected at write time by `validate_last_event()` in `phase_helpers.py`.

| Constant | String Value | Display Label | Emitted By | Consumed By | Transitions To |
|---|---|---|---|---|---|
| `EVENT_FEATURE_CREATED` | `feature_created` | `starting up` | `state_store.create_feature_files()` | — | — |
| `EVENT_RESUMED` | `resumed` | `resumed` | `sessions.prepare_resumed_session()` | `reviewing` phase enter | — |
| `EVENT_PM_COMPLETED` | `pm_completed` | `pm done` | `ProductManagementHandler` | — | `architecting` |
| `EVENT_ARCHITECTURE_WRITTEN` | `architecture_written` | `architecture ready` | `ArchitectingHandler` | — | `planning` |
| `EVENT_PLAN_WRITTEN` | `plan_written` | `plan ready` | `PlanningHandler` | `implementing` enter | `designing`, `implementing` |
| `EVENT_DESIGN_WRITTEN` | `design_written` | `design ready` | `DesigningHandler` | `implementing` enter | `implementing` |
| `EVENT_IMPLEMENTATION_COMPLETED` | `implementation_completed` | `code done` | `ImplementingHandler`, `FixingHandler` | — | `reviewing` |
| `EVENT_REVIEW_FAILED` | `review_failed` | `fix needed` | `ReviewingHandler` | `fixing` enter | `fixing`, `completing` |
| `EVENT_REVIEW_PASSED` | `review_passed` | `review passed` | `ReviewingHandler` | — | — |
| `EVENT_CHANGES_REQUESTED` | `changes_requested` | `changes asked` | `CompletingHandler` | `planning` enter, `implementing` enter | `planning` |
| `EVENT_RUN_CANCELED` | `run_canceled` | `canceled` | orchestrator interruption | — | `failed` |
| `EVENT_RUN_FAILED` | `run_failed` | `run failed` | orchestrator interruption | — | `failed` |

The table above summarizes runtime behavior from three sources: event metadata in `event_catalog.py`, phase emission wiring in `phase_registry.py`, and the phase-local consumption/transition logic in the individual handler modules.
