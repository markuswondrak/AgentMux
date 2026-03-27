# Monitor Display

> Related source files: `agentmux/monitor/__init__.py`, `agentmux/monitor/state_reader.py`, `agentmux/monitor/render.py`, `agentmux/terminal_ui/layout.py`

The control pane renders a live status box with the following sections:

- **Feature request** — the initial feature description from `requirements.md`
- **Pipeline stages** — progress through the workflow (`product_management`, `planning`, `implementing`, `reviewing`, `completing`, `done`)
  - Always-visible stages: `product_management`, `planning`, `implementing`, `reviewing`, `completing`
  - Optional phases (shown only when active): `designing`, `fixing`
  - Displayed with `▶` for active, `·` for inactive
- **Pipeline metadata** — human-readable event label (e.g. "plan ready" for `plan_written`), review iteration count, subplan count
  - During staged implementation, metadata also shows execution group details:
    - active execution group index / total groups
    - active group mode (`serial` or `parallel`)
    - overall progress through all execution groups
  - For legacy flat plans, monitor falls back to subplan-count-only metadata
- **Agents** — list of active agents only (WORKING/IDLE), with provider/model info
  - Inactive agents are filtered out of the AGENTS section
  - For parallel coder mode, only non-inactive `coder_<n>` workers are shown
  - Agent rows use a shared `[role] secondary-info` format
  - Coder rows prefer the explicit `name` from `02_planning/execution_plan.json`, then fall back to the `## Sub-plan <N>: <title>` header in `02_planning/plan_<n>.md`
  - Reviewer rows show the current review iteration, and designer rows show the feature being designed
- **Research tasks** — progress on code and web research (if any)
- **Event log** — recent timeline entries with timestamps: phase transitions plus filtered handover-relevant file creations from `created_files.log`
  - Phase-transition entries are rendered in white for contrast
  - Includes workflow artifacts such as `plan.md`, `tasks.md`, research `summary.md` / `detail.md` / `done`, `design.md`, review handoff files, implementation `done_*`, and completion artifacts
  - Excludes runtime noise such as `context.md`, prompt files, request files, temp files, and other orchestration internals

## Key constants

- `ALWAYS_VISIBLE_STATES` — phases shown in all cases
- `OPTIONAL_PHASES` — phases hidden until they are the active phase
- `EVENT_LABELS` — mapping of internal event names (e.g. `plan_written`) to user-friendly labels (e.g. "plan ready")

## Staged implementation display notes

- The monitor should represent implementing as grouped work, not only a single undifferentiated `implementing` phase.
- Group labels are derived from orchestrator-managed state and should stay consistent with `02_planning/execution_plan.json`.
- If staged fields are absent (older sessions), rendering remains compatible with legacy flat sub-plan execution.

## Component split

- `agentmux/monitor/__init__.py` owns the monitor command loop and pane refresh cadence
- `agentmux/monitor/state_reader.py` owns runtime-state inspection, log parsing, and event label mapping
- `agentmux/monitor/render.py` owns ANSI rendering and screen composition
