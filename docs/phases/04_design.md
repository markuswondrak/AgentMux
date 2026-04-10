# Phase: Design

> Directory: `04_design/` | Optional: yes (activated when `needs_design: true` in `plan.yaml`)

The designer produces a detailed design document before implementation begins, used when the plan flags a need for a separate design handoff step.

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `designer_prompt.md` | orchestrator | designer agent | Markdown prompt |
| `design.md` | designer agent | coder agents (via prompt injection) | Markdown |

## Transitions

| From | Event | To |
|------|-------|----|
| `planning` | `plan_written` with `needs_design: true` | `designing` |
| `designing` | `design_written` (on `design.md` submitted) | `implementing` |

## Notes

- Skipped when `needs_design: false` in `plan.yaml`; the pipeline moves directly from `planning` to `implementing`.
- The monitor shows this phase only when it is active (optional phase).
- The need for a design phase is typically flagged by the product-manager or architect during their respective phases. The planner then captures this signal as `needs_design: true` in `plan.yaml`, which drives the `planning → designing` transition.
