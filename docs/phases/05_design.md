# Phase: Design

> Related source files: `src/agentmux/workflow/handlers/designing.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/prompts.py`
> Directory: `05_design/` | Optional: yes (activated when `needs_design: true` in `plan.yaml`)

The designer produces a detailed design document before implementation begins, used when the plan flags a need for a separate design handoff step.

## Conditions

Activated when the planner sets `needs_design: true` in `plan.yaml`. Skipped otherwise; the pipeline moves directly from `planning` to `implementing`.

## Role

**designer** agent — reads architecture, plan, and requirements, then produces `design.md`.

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

- The monitor shows this phase only when it is active (optional phase).
- The need for a design phase is typically flagged by the product-manager or architect during their respective phases. The planner then captures this signal as `needs_design: true` in `plan.yaml`, which drives the `planning → designing` transition.
