# Artifact: state.json

> Related source files: `src/agentmux/sessions/state_store.py`, `src/agentmux/workflow/phase_registry.py`

`state.json` is the primary durable state file for a pipeline session. It lives at the root of the feature directory and is read/written exclusively by the orchestrator. Agents never write to it directly.

## Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `phase` | string | yes | Current workflow phase name (e.g. `"architecting"`, `"implementing"`, `"completing"`). See [phase sequence](../phases/index.md). |
| `last_event` | string | yes | The most recent workflow event that drove the last transition. See [event catalog](../file-protocol.md#workflow-events). |
| `product_manager` | bool | yes | Whether the pipeline was started with `--product-manager`. Controls product management phase activation and resume logic. |
| `subplan_count` | int | yes | Total number of sub-plans in the current execution plan. Set when `plan.yaml` is processed. |
| `completed_subplans` | string[] | yes | List of completed sub-plan IDs (e.g. `["1", "2"]`). Used by the implementing phase to track per-coder progress. |
| `review_iteration` | int | yes | Number of review/fix cycles completed. Compared against the configured loop cap to decide whether to fix or complete after a fail verdict. |
| `implementation_group_total` | int | yes | Total number of execution groups in `execution_plan.yaml`. |
| `implementation_group_index` | int | yes | 1-based index of the currently active execution group. |
| `implementation_group_mode` | string \| null | yes | Execution mode of the active group: `"serial"` or `"parallel"`. `null` before implementation starts. |
| `implementation_active_plan_ids` | string[] | yes | Plan IDs currently dispatched for the active group. |
| `implementation_completed_group_ids` | string[] | yes | Ordered list of completed `group_id` values from `execution_plan.yaml`. |
| `updated_at` | string | yes | ISO-8601 timestamp of the last state write. |
| `updated_by` | string | yes | Identifier of the component that last wrote state (e.g. `"pipeline"`, handler class name). |
| `feature_dir` | string | yes | Absolute path to the feature directory. |
| `session_name` | string | yes | tmux session name for this pipeline run. |
| `gh_available` | bool | no | Set at startup if `gh` CLI is available and the repo is a GitHub repo. Controls branch/PR creation at completion. |
| `issue_number` | int | no | GitHub issue number when started with `agentmux issue <N>`. Used to add `Closes #<N>` to the PR body. |
| `research_tasks` | dict | no | Tracks code-researcher task status by topic key. Each value is a status string (`"dispatched"`, `"done"`). |
| `web_research_tasks` | dict | no | Tracks web-researcher task status by topic key. Each value is a status string (`"dispatched"`, `"done"`). |
| `awaiting_summary` | bool | no | Set to `true` by the reviewing handler when the reviewer is asked to write `summary.md`. Cleared when the summary appears. |

## Example

```json
{
  "phase": "implementing",
  "last_event": "plan_written",
  "product_manager": false,
  "subplan_count": 2,
  "completed_subplans": ["1"],
  "review_iteration": 0,
  "implementation_group_total": 1,
  "implementation_group_index": 1,
  "implementation_group_mode": "serial",
  "implementation_active_plan_ids": ["2"],
  "implementation_completed_group_ids": [],
  "updated_at": "2024-01-15T10:30:00+00:00",
  "updated_by": "ImplementingHandler",
  "feature_dir": "/home/user/myproject/.agentmux/.sessions/20240115-103000-my-feature",
  "session_name": "agentmux-my-feature"
}
```

---

# Artifact: runtime_state.json

> Related source files: `src/agentmux/runtime/tmux_control.py`, `src/agentmux/sessions/state_store.py`

`runtime_state.json` stores ephemeral runtime information about the active tmux session. It is written by the tmux runtime layer and read by the orchestrator for pane management. Unlike `state.json`, it is not preserved across restarts in a meaningful way.

## Schema

| Field | Type | Description |
|-------|------|-------------|
| `tmux_session` | string | tmux session name |
| `panes` | dict | Map of role name → tmux pane ID (e.g. `{"architect": "%1", "coder": "%2"}`) |

---

# Artifact: tool_event_state.json

> Related source files: `src/agentmux/runtime/tool_events.py`

`tool_event_state.json` persists the applied-cursor for `tool_events.jsonl`. The orchestrator writes this after each tool event is handled so that a resumed session replays only unapplied events.

## Schema

| Field | Type | Description |
|-------|------|-------------|
| `applied_offset` | int | Byte offset in `tool_events.jsonl` up to which events have been applied. |

## Example

```json
{
  "applied_offset": 1024
}
```
