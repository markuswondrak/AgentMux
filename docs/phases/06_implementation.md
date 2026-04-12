# Phase: Implementation (Implementing + Fixing)

> Related source files: `src/agentmux/workflow/handlers/implementing.py`, `src/agentmux/workflow/handlers/fixing.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/prompts.py`, `src/agentmux/integrations/mcp_server.py`
> Directory: `06_implementation/` (shared by `implementing` and `fixing` phases) | Optional: no (implementing); yes (fixing)

Implementation executes the execution plan produced by planning. Coders receive numbered prompt files mapped to scheduled plan units. After a failed review, the fixing sub-phase runs in the same directory.

## Conditions

**Implementing:** entered after planning (or designing) completes.
**Fixing:** entered after a `review_failed` event, as long as the review loop cap has not been reached.

## Role

**coder** agent — receives a per-plan prompt and implements or fixes the assigned sub-plan. One coder is spawned per active plan in a parallel group; serial groups spawn one at a time.

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

After a `review_fail` event (and below the review loop cap), the pipeline re-enters `06_implementation/` for a fixing pass. The fix prompt is injected based on `07_review/fix_request.md` (see [review.md](review.md)). Fixing completion is signaled by writing `done_1`.

## Transitions

| From | Event | To |
|------|-------|----|
| `planning` or `designing` | `plan_written` / `design_written` | `implementing` |
| `implementing` | `implementation_completed` | `reviewing` |
| `reviewing` | `review_failed` (below loop cap) | `fixing` |
| `fixing` | `implementation_completed` | `reviewing` |
| `reviewing` | `review_failed` (loop cap reached) | `completing` |

## Notes

- `implementing` and `fixing` share the same directory (`06_implementation/`); they differ only in how the prompt is built (plan vs. fix-request).
- Each coder receives only its assigned `plan_<N>.md` and `tasks_<N>.md`; coders for different sub-plans never see each other's prompts.
- See [Artifact: state.json](../artifacts/session-state.md) for the implementation scheduling fields (`implementation_group_*`).
