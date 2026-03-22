# Monitor Display

> Related source files: `src/monitor.py`

The control pane renders a live status box with the following sections:

- **Feature request** — the initial feature description from `requirements.md`
- **Pipeline stages** — progress through the workflow (planning, implementing, reviewing, completing, done)
  - Always-visible stages: `planning`, `implementing`, `reviewing`, `completing`
  - Optional phases (shown only when active): `designing`, `fixing`, `documenting`
  - Displayed with `▶` for active, `·` for inactive
- **Pipeline metadata** — human-readable event label (e.g. "plan ready" for `plan_written`), review iteration count, subplan count
- **Agents** — list of all agents with their status (●WORKING / ●IDLE / ○inactive) and provider/model info
- **Research tasks** — progress on code and web research (if any)
- **Documents** — workflow output files present: `planning/plan.md`, `planning/tasks.md`, `design/design.md`, `review/review.md`, `completion/changes.md` (shown with ✓ when present)
- **Event log** — recent phase transitions with timestamps

## Key constants

- `ALWAYS_VISIBLE_STATES` — phases shown in all cases
- `OPTIONAL_PHASES` — phases hidden until they are the active phase
- `EVENT_LABELS` — mapping of internal event names (e.g. `plan_written`) to user-friendly labels (e.g. "plan ready")
- `DOCUMENT_FILES` — list of workflow output files to track
