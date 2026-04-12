# Artifact: Event Logs

> Related source files: `src/agentmux/runtime/tool_events.py`, `src/agentmux/runtime/file_events.py`, `src/agentmux/integrations/mcp_server.py`

Two append-only log files are maintained at the root of the feature directory throughout a pipeline run.

---

## `tool_events.jsonl`

**Location:** `<feature_dir>/tool_events.jsonl`

An append-only JSONL file (one JSON object per line) that records every MCP tool call made by agents. The orchestrator's `ToolCallEventSource` tails this file via watchdog and emits `SessionEvent` objects into the `EventBus`, driving state transitions.

### Entry shape

Each line is a JSON object:

```json
{"tool": "<tool_name>", "timestamp": "<ISO-8601>", "payload": {...}}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool` | string | Name of the MCP tool that was called. See [tool names](#tool-names). |
| `timestamp` | string | ISO-8601 datetime of when the tool call was recorded. |
| `payload` | dict | Tool-specific data. Most tools write `{}` (empty object); `submit_done` includes `{"subplan_index": N}`. |

### Tool names

| Tool | Payload | Effect |
|------|---------|--------|
| `submit_architecture` | `{}` | Signals architect completion; drives `architecting → planning`. |
| `submit_plan` | `{}` | Signals planner completion; orchestrator materializes derived plan artifacts. |
| `submit_review` | `{}` | Signals reviewer completion; orchestrator reads `review.yaml` for verdict. |
| `submit_done` | `{"subplan_index": N}` | Signals one coder sub-plan completion. |
| `submit_research_done` | `{}` | Signals code-researcher or web-researcher task completion. |
| `submit_pm_done` | `{}` | Signals product manager completion; drives `product_management → architecting`. |

### Resume behavior

The orchestrator persists an applied-cursor in `tool_event_state.json` after each event is handled. On resume, only events after the cursor are replayed, preventing double-processing of already-handled submissions.

### Example entries

```jsonl
{"tool": "submit_architecture", "timestamp": "2024-01-15T10:15:30+00:00", "payload": {}}
{"tool": "submit_plan", "timestamp": "2024-01-15T10:22:45+00:00", "payload": {}}
{"tool": "submit_done", "timestamp": "2024-01-15T11:05:12+00:00", "payload": {"subplan_index": 1}}
{"tool": "submit_review", "timestamp": "2024-01-15T11:30:00+00:00", "payload": {}}
```

---

## `created_files.log`

**Location:** `<feature_dir>/created_files.log`

An append-only text log that records the first time each file is created within the feature directory. Used by the monitor to display file activity and by developers to trace what was produced during a run.

### Format

Each line has the form:

```
YYYY-MM-DD HH:MM:SS  relative/path/to/file
```

- Timestamp is local time (no timezone offset).
- Path is relative to the feature directory.
- Each path appears at most once (deduplicated by the logger).
- Directories are not logged — only files.

### Seeding

At startup, the orchestrator seeds the log with any pre-existing files in the feature directory (e.g. `state.json`, `requirements.md`, `context.md`) so they appear in the log even though they were not created during the watchdog observation window.

### Example

```
2024-01-15 10:00:01  state.json
2024-01-15 10:00:01  requirements.md
2024-01-15 10:00:01  context.md
2024-01-15 10:15:30  02_architecting/architect_prompt.md
2024-01-15 10:15:45  02_architecting/architecture.md
2024-01-15 10:22:30  04_planning/planner_prompt.md
2024-01-15 10:22:45  04_planning/plan.yaml
```
