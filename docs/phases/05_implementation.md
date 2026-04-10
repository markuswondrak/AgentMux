# Phase: Implementation (Implementing + Fixing)

> Directory: `05_implementation/` (shared by `implementing` and `fixing` phases) | Optional: no (implementing); yes (fixing)

Implementation executes the execution plan produced by planning. Coders receive numbered prompt files mapped to scheduled plan units. After a failed review, the fixing sub-phase runs in the same directory.

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `coder_prompt_<N>.md` | orchestrator | coder agent N | Markdown |
| `done_<N>` | coder agent N (via `submit_done`) | orchestrator | empty marker |
| `done_1` | coder agent (fixing phase) | orchestrator | empty marker |

## Scheduling metadata (in `state.json`)

| Key | Type | Purpose |
|-----|------|---------|
| `implementation_group_total` | int | Total number of scheduled execution groups |
| `implementation_group_index` | int | Current 1-based active group index |
| `implementation_group_mode` | `serial`/`parallel` | Active group execution mode |
| `implementation_active_plan_ids` | string[] | Active `plan_<N>` IDs for the current group |
| `implementation_completed_group_ids` | string[] | Ordered list of completed `group_id` values |

## Execution scheduling

- `execution_plan.yaml` (materialized from `plan.yaml`) must exist before implementation starts.
- Groups execute in order; within a group, `serial` dispatches one plan at a time, `parallel` dispatches all simultaneously.
- Each coder receives only its assigned plan's `plan_<N>.md` and `tasks_<N>.md`.

## Fixing {#fixing}

After a `review_fail` event (and below the review loop cap), the pipeline re-enters `05_implementation/` for a fixing pass. The fix prompt is injected based on `06_review/fix_request.md` (see [review.md](review.md)). Fixing completion is signaled by writing `done_1`.

## Transitions

| From | Event | To |
|------|-------|----|
| `planning` or `designing` | `plan_written` / `design_written` | `implementing` |
| `implementing` | `implementation_completed` | `reviewing` |
| `reviewing` | `review_failed` (below loop cap) | `fixing` |
| `fixing` | `implementation_completed` | `reviewing` |
| `reviewing` | `review_failed` (loop cap reached) | `completing` |
