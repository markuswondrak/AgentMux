# Monitor Display

> Related source files: `agentmux/monitor.py`

The control pane renders a live status box with the following sections:

- **Feature request** — the initial feature description from `requirements.md`
- **Pipeline stages** — progress through the workflow (`product_management`, `planning`, `implementing`, `reviewing`, `completing`, `done`)
  - Always-visible stages: `product_management`, `planning`, `implementing`, `reviewing`, `completing`
  - Optional phases (shown only when active): `designing`, `fixing`, `documenting`
  - Displayed with `▶` for active, `·` for inactive
- **Pipeline metadata** — human-readable event label (e.g. "plan ready" for `plan_written`), review iteration count, subplan count
- **Agents** — list of active agents only (WORKING/IDLE), with provider/model info
  - Inactive agents are filtered out of the AGENTS section
  - For parallel coder mode, only non-inactive `coder_<n>` workers are shown
- **Research tasks** — progress on code and web research (if any)
- **Documents** — workflow output files present: `02_planning/plan.md`, `02_planning/tasks.md`, `04_design/design.md`, `06_review/review.md`, `08_completion/changes.md` (shown with ✓ when present)
- **Event log** — recent timeline entries with timestamps: phase transitions plus filtered handover-relevant file creations from `created_files.log`
  - Includes workflow artifacts such as `plan.md`, `tasks.md`, research `summary.md` / `detail.md` / `done`, `design.md`, review handoff files, implementation `done_*`, and completion artifacts
  - Excludes runtime noise such as `context.md`, prompt files, request files, temp files, and other orchestration internals

## Key constants

- `ALWAYS_VISIBLE_STATES` — phases shown in all cases
- `OPTIONAL_PHASES` — phases hidden until they are the active phase
- `EVENT_LABELS` — mapping of internal event names (e.g. `plan_written`) to user-friendly labels (e.g. "plan ready")
- `DOCUMENT_FILES` — list of workflow output files to track
