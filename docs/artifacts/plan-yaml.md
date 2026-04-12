# Artifact: plan.yaml

> Related source files: `src/agentmux/workflow/handoff_contracts.py`, `src/agentmux/workflow/handlers/planning.py`, `src/agentmux/integrations/mcp_server.py`

`plan.yaml` is the canonical execution plan produced by the planner agent and submitted via the `submit_plan` MCP tool. It must use schema version 2. The orchestrator materializes all derived artifacts (`plan_<N>.md`, `tasks_<N>.md`, `execution_plan.yaml`, `plan.md`) from this single file.

**Location:** `04_planning/plan.yaml`

## Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | int | yes | Must be `2`. |
| `plan_overview` | string | yes | Human-readable summary of the plan. Becomes the content of `plan.md`. |
| `review_strategy` | dict | yes | Review configuration. See [review_strategy fields](#review_strategy-fields). |
| `needs_design` | bool | yes | Whether a design phase is required before implementation. Controls `planning → designing` vs `planning → implementing` transition. |
| `needs_docs` | bool | yes | Whether documentation updates are in scope. Informational only — does not affect transitions. |
| `doc_files` | string[] | yes | Planned documentation files to create or update. May be empty (`[]`). |
| `groups` | list[dict] | yes | Execution groups defining the scheduling order. See [groups fields](#groups-fields). Must have at least one group. |
| `subplans` | list[dict] | yes | Sub-plans for the coder agents. See [subplans fields](#subplans-fields). Must have at least one sub-plan. |

## `review_strategy` fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `severity` | string | yes | Risk level: `"low"`, `"medium"`, or `"high"`. Controls reviewer type selection. |
| `focus` | string[] | no | Specific review focus areas. Valid values: `"security"`, `"performance"`, `"testing"`, `"error-handling"`, `"accessibility"`, `"documentation"`, `"maintainability"`. When `severity` is `medium` or `high` and `focus` contains `"security"` or `"performance"`, the expert reviewer is selected. |

## `groups` fields

Each entry in `groups` defines an execution group:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `group_id` | string | yes | Unique identifier for this group (e.g. `"core-setup"`, `"api-layer"`). Must be unique across all groups. |
| `mode` | string | yes | Execution mode: `"serial"` (one sub-plan at a time in order) or `"parallel"` (all sub-plans simultaneously). |
| `plans` | list[dict] | yes | Sub-plan references in this group. Each entry: `{index: int, name: string}`. Must reference valid subplan indices. Non-empty. |

## `subplans` fields

Each entry in `subplans` defines a sub-plan delivered to a coder agent:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `index` | int | yes | 1-based unique integer. Must be contiguous from 1 to N. Referenced by `groups[].plans[].index`. |
| `title` | string | yes | Short descriptive title shown in the monitor and plan summary. |
| `scope` | string | yes | What this sub-plan covers (which part of the system). |
| `owned_files` | string[] | yes | Files this sub-plan is responsible for creating or modifying. Non-empty. |
| `dependencies` | string | yes | Description of what must exist before this sub-plan runs (or `"None"`). |
| `implementation_approach` | string | yes | Step-by-step description of how to implement this sub-plan. |
| `acceptance_criteria` | string | yes | Conditions that must be met for this sub-plan to be considered done. |
| `tasks` | string[] | yes | Ordered checklist of implementation tasks. Non-empty. |
| `isolation_rationale` | string | no | Optional note on why this sub-plan is isolated / why it can be parallelized. |

## Validation rules

- `version` must be exactly `2`.
- All subplan `index` values must be unique and contiguous from `1` to the count of subplans.
- All group `group_id` values must be unique.
- Every subplan index must be referenced by exactly one group entry.
- Every group plan reference must have a matching subplan.
- `groups[].mode` must be `"serial"` or `"parallel"`.

## Example

```yaml
version: 2
plan_overview: |
  Add JWT authentication to the API. Covers token generation, validation
  middleware, and protected route guards.
review_strategy:
  severity: medium
  focus: [security]
needs_design: false
needs_docs: true
doc_files: [docs/auth.md]
groups:
  - group_id: auth-core
    mode: serial
    plans:
      - index: 1
        name: JWT token service
      - index: 2
        name: Auth middleware
subplans:
  - index: 1
    title: JWT token service
    scope: Token generation and validation logic
    owned_files: [src/auth/tokens.py, tests/test_tokens.py]
    dependencies: None
    implementation_approach: |
      Implement generate_token() and validate_token() using PyJWT.
      Store secret in config. Add expiry handling.
    acceptance_criteria: Unit tests pass for generate and validate.
    tasks:
      - Create src/auth/tokens.py with generate_token and validate_token
      - Write tests/test_tokens.py with happy-path and expiry tests
  - index: 2
    title: Auth middleware
    scope: Request authentication middleware for FastAPI
    owned_files: [src/auth/middleware.py, src/main.py]
    dependencies: JWT token service (index 1)
    implementation_approach: |
      Create FastAPI dependency that extracts Bearer token from
      Authorization header and calls validate_token().
    acceptance_criteria: Protected routes return 401 on missing/invalid token.
    tasks:
      - Create src/auth/middleware.py with get_current_user dependency
      - Wire middleware into src/main.py for protected routes
```

## Derived artifacts

The orchestrator materializes these files from `plan.yaml`:

| Artifact | Description |
|----------|-------------|
| `plan.md` | Human-readable plan summary from `plan_overview` |
| `plan_<N>.md` | Per-sub-plan implementation prompt for coder N |
| `tasks_<N>.md` | Per-sub-plan task checklist for coder N |
| `execution_plan.yaml` | Scheduling metadata consumed by the implementation phase |
