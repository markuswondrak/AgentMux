# Phase: Planning (Architecting + Planning + Research)

> Directory: `02_planning/` (shared by `architecting` and `planning` phases) | Optional: no
> Research directory: `03_research/` | Optional: on-demand

Planning covers two sequential sub-phases that share the same directory, plus on-demand research tasks spawned by the architect.

## Sub-phases

### Architecting

The architect produces a technical architecture document describing *what* will be built and *with what* tools/libraries. It may also spawn research tasks (code or web) before submitting.

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `architect_prompt.md` | orchestrator | architect agent | Markdown prompt |
| `changes_prompt.md` | orchestrator | architect agent (on replanning) | Markdown |
| `architecture.md` | architect agent (via `submit_architecture`) | planner (via prompt injection) | Markdown |

### Planning

The planner converts the architecture into an execution plan with sub-plans, scheduling groups, and implementation tasks.

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `planner_prompt.md` | orchestrator | planner agent | Markdown prompt |
| `plan.yaml` | planner agent (via `submit_plan`) | orchestrator | YAML v2 |
| `plan.md` | orchestrator (from `plan.yaml`) | humans | Markdown |
| `plan_<N>.md` | orchestrator (from `plan.yaml`) | coder agents | Markdown |
| `tasks_<N>.md` | orchestrator (from `plan.yaml`) | coder agents | Markdown |
| `execution_plan.yaml` | orchestrator (from `plan.yaml`) | scheduler | YAML v1 |
| `tasks.md` | orchestrator (from `plan.yaml`, optional) | humans | Markdown |

See [Handoff Contracts](../handoff-contracts.md#plan) for the full `plan.yaml` v2 schema.

## Execution scheduling (`execution_plan.yaml`)

The orchestrator materializes `execution_plan.yaml` from `plan.yaml` execution groups. This file drives the coder's task ordering.

- Execution scheduling is strict: `execution_plan.yaml` must exist before implementation starts.
- Each group has a unique `group_id` and an execution mode (`serial` or `parallel`).
- `serial` groups execute plans one at a time in order.
- `parallel` groups execute all plans simultaneously.
- Plan entries use a YAML mapping with `file` and `name` keys (for example `- file: plan_1.md` followed by `name: Core setup`)

## Research (`03_research/`)

Research tasks are spawned on-demand by the architect during the architecting phase. Each task gets its own subdirectory.

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `code-<topic>/request.md` | architect agent | code-researcher agent | Markdown |
| `code-<topic>/prompt.md` | orchestrator | code-researcher agent | Markdown prompt |
| `code-<topic>/summary.md` | code-researcher agent | architect (via prompt) | Markdown |
| `code-<topic>/detail.md` | code-researcher agent | architect (via prompt) | Markdown |
| `code-<topic>/done` | code-researcher agent | orchestrator | empty marker |
| `web-<topic>/request.md` | architect agent | web-researcher agent | Markdown |
| `web-<topic>/prompt.md` | orchestrator | web-researcher agent | Markdown prompt |
| `web-<topic>/summary.md` | web-researcher agent | architect (via prompt) | Markdown |
| `web-<topic>/detail.md` | web-researcher agent | architect (via prompt) | Markdown |
| `web-<topic>/done` | web-researcher agent | orchestrator | empty marker |

## Transitions

| From | Event | To |
|------|-------|----|
| `product_management` or pipeline start | — | `architecting` |
| `architecting` | `architecture_written` (on `architecture.md` submitted) | `planning` |
| `planning` | `plan_written` (on `plan.yaml` submitted) | `designing` or `implementing` |
| `completing` | `changes_requested` | `architecting` (re-planning) |

## `plan.yaml` metadata fields

| Field | Type | Purpose |
|-------|------|---------|
| `needs_design` | bool | Whether to run the designing phase before implementation |
| `needs_docs` | bool | Whether documentation updates are in scope (informational) |
| `doc_files` | string[] | Planned documentation targets |
| `review_strategy.severity` | `low`/`medium`/`high` | Risk level; controls which reviewer type is used |
| `review_strategy.focus` | string[] | Specific review focus areas |
