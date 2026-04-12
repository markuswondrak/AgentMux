# Shared File Protocol

> Related source file: `src/agentmux/workflow/orchestrator.py`

Agents communicate via files in `.agentmux/.sessions/<feature-name>/`. Files are grouped by phase subdirectories and created on-demand as needed, while a small set of root runtime artifacts is maintained directly by the orchestrator.

## Root files

- `state.json` — current workflow phase and all scheduling state. See [artifacts/session-state.md](artifacts/session-state.md#artifact-statejson).
- `requirements.md` — initial request passed to architect
- `context.md` — auto-generated rules/session info injected into prompts
- `runtime_state.json` / `orchestrator.log` — runtime tracking and orchestrator logs. See [artifacts/session-state.md](artifacts/session-state.md#artifact-runtime_statejson).
- `created_files.log` — append-only created-file history. See [artifacts/event-logs.md](artifacts/event-logs.md#created_fileslog).
- `tool_events.jsonl` — append-only MCP tool-call event log. See [artifacts/event-logs.md](artifacts/event-logs.md#tool_eventsjsonl).
- `tool_event_state.json` — persisted tool-event replay cursor. See [artifacts/session-state.md](artifacts/session-state.md#artifact-tool_event_statejson).

## Phase artifacts

For the full artifact listing per phase (files, writers, readers, formats, and transitions), see **[docs/phases/](phases/index.md)**:

- [Product Management](phases/01_product-management.md) — `01_product_management/`
- [Architecting](phases/02_architecting.md) — `02_architecting/` and `03_research/`
- [Planning](phases/04_planning.md) — `04_planning/`
- [Design](phases/05_design.md) — `05_design/`
- [Implementation](phases/06_implementation.md) — `06_implementation/`
- [Review](phases/07_review.md) — `07_review/`
- [Completion](phases/08_completion.md) — `08_completion/`

See also **[docs/artifacts/](artifacts/index.md)** for full schema documentation of key session artifacts.

## Key functions

- `PipelineOrchestrator.run()` / `build_event_bus()` in `src/agentmux/workflow/orchestrator.py` — run the phase loop on top of a shared session event bus
- `EventBus` in `src/agentmux/runtime/event_bus.py` — generic dispatcher plus start/stop lifecycle for dedicated event sources
- `FileEventSource` / `FeatureEventHandler` in `src/agentmux/runtime/file_events.py` — normalize watchdog activity under the feature directory and publish `file.*` events
- `CreatedFilesLogListener` / `seed_existing_files()` in `src/agentmux/runtime/file_events.py` — enforce created-file logging semantics (`created_files.log`, first-seen only, bootstrap coverage)
- `ToolCallEventSource` in `src/agentmux/runtime/tool_events.py` — tail `tool_events.jsonl` and publish `tool.<name>` events into the EventBus; seeded at startup, then watched via watchdog
- `InterruptionEventSource` in `src/agentmux/runtime/interruption_sources.py` — publish interruption events when registered tmux panes disappear
- `WorkflowEventRouter.enter_current_phase()` in `src/agentmux/workflow/event_router.py` — explicitly bootstraps the active phase before steady-state event processing starts
- `build_*_prompt()` in `src/agentmux/workflow/prompts.py` — loads and renders the markdown template for each phase; called lazily by handlers
- Handler functions in `src/agentmux/workflow/handlers/` — each builds and writes its prompt file just before sending to agent

## MCP Tool Event Protocol

When agents call MCP tools (`submit_architecture`, `submit_plan`, `submit_review`, `submit_done`, `submit_research_done`, `submit_pm_done`), the submission tools read the agent-written file, validate it, and append a minimal signal entry to `tool_events.jsonl`. Validation errors are returned immediately so agents can correct their files. The tools write no workflow artifacts themselves — agents always own writing the output files.

Each entry has this shape:

```json
{"tool": "<tool_name>", "timestamp": "<ISO-8601>", "payload": {...}}
```

`ToolCallEventSource` tails `tool_events.jsonl` and emits `SessionEvent(kind="tool.<name>")` events into the `EventBus`. The orchestrator persists an applied cursor in `tool_event_state.json` after each tool event is handled, so resume replays only unapplied signals. The `WorkflowEventRouter` routes tool events via `ToolSpec` to the appropriate phase handler, which materializes `.md` companions from the agent-written `.yaml` (if missing) and drives state transitions.

Agents write workflow artifact YAML files directly. The MCP submission tools validate the agent-written file and signal the orchestrator to advance — they do not write files themselves.

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
