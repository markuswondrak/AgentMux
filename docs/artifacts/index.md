# Session Artifacts

> Related source files: `src/agentmux/sessions/state_store.py`, `src/agentmux/workflow/handoff_contracts.py`, `src/agentmux/integrations/mcp_server.py`, `src/agentmux/runtime/tool_events.py`, `src/agentmux/runtime/file_events.py`

This directory documents the important session artifacts produced and consumed during a pipeline run. Each file in `.agentmux/.sessions/<feature-name>/` serves a defined role in the workflow.

## Artifact groups

| Document | Artifacts covered |
|----------|-------------------|
| [session-state.md](session-state.md) | `state.json`, `runtime_state.json`, `tool_event_state.json` |
| [plan-yaml.md](plan-yaml.md) | `04_planning/plan.yaml` (v2 schema) |
| [review-yaml.md](review-yaml.md) | `07_review/review.yaml` |
| [completion-artifacts.md](completion-artifacts.md) | `08_completion/approval.json`, `08_completion/changes.md`, `.agentmux/.last_completion.json` |
| [event-logs.md](event-logs.md) | `tool_events.jsonl`, `created_files.log` |

## Root session files (quick reference)

These files live directly in the feature directory (`.agentmux/.sessions/<feature>/`):

| File | Writer | Description |
|------|--------|-------------|
| `state.json` | orchestrator | Workflow phase and all scheduling state. See [session-state.md](session-state.md). |
| `requirements.md` | pipeline (on start) | Initial feature request passed to the architect. |
| `context.md` | pipeline (on start) | Auto-generated session context injected into agent prompts. |
| `runtime_state.json` | orchestrator | Runtime tracking (pane IDs, tmux session name). See [session-state.md](session-state.md). |
| `orchestrator.log` | orchestrator | Human-readable orchestration log (append-only). |
| `created_files.log` | orchestrator | Append-only record of first-seen created files. See [event-logs.md](event-logs.md). |
| `tool_events.jsonl` | MCP server | Append-only structured tool-call event log. See [event-logs.md](event-logs.md). |
| `tool_event_state.json` | orchestrator | Replay cursor for `tool_events.jsonl`. See [session-state.md](session-state.md). |

## Phase artifacts (quick reference)

Phase-specific artifacts live in numbered subdirectories. For full artifact tables (writer, reader, format) per phase see **[docs/phases/](../phases/index.md)**.

| Phase directory | Key artifacts |
|-----------------|---------------|
| `01_product_management/` | `done` |
| `02_architecting/` | `architecture.md` |
| `03_research/` | `code-<topic>/summary.md`, `web-<topic>/summary.md` |
| `04_planning/` | `plan.yaml` (→ [plan-yaml.md](plan-yaml.md)), `execution_plan.yaml`, `plan_<N>.md` |
| `05_design/` | `design.md` |
| `06_implementation/` | `coder_prompt_<N>.md`, `done_<N>` |
| `07_review/` | `review.yaml` (→ [review-yaml.md](review-yaml.md)), `review.md` |
| `08_completion/` | `approval.json`, `changes.md`, `summary.md` (→ [completion-artifacts.md](completion-artifacts.md)) |
