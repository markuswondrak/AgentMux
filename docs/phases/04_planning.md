# Phase: Planning

> Related source files: `src/agentmux/workflow/handlers/planning.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/prompts.py`, `src/agentmux/integrations/mcp_server.py`
> Directory: `04_planning/` | Optional: no

The planner converts the architecture document (`02_architecting/architecture.md`) into an execution plan with sub-plans, scheduling groups, and implementation tasks. Research results from `03_research/` are injected into the planner prompt if available.

## Conditions

Entered after `architecting` completes (`architecture_written` event). Also re-entered when the user requests changes at completion (`changes_requested` event), receiving updated architecture.

## Role

**planner** agent — reads `architecture.md` and produces `plan.yaml`.

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `planner_prompt.md` | orchestrator | planner agent | Markdown prompt |
| `plan.yaml` | planner agent (via `submit_plan`) | orchestrator | YAML v2 |
| `plan.md` | orchestrator (from `plan.yaml`) | humans | Markdown |
| `plan_<N>.md` | orchestrator (from `plan.yaml`) | coder agents | Markdown |
| `tasks_<N>.md` | orchestrator (from `plan.yaml`) | coder agents | Markdown |
| `execution_plan.yaml` | orchestrator (from `plan.yaml`) | scheduler | YAML v1 |
| `tasks.md` | orchestrator (from `plan.yaml`, optional) | humans | Markdown |

See [Artifact: plan.yaml](../artifacts/plan-yaml.md) for the full `plan.yaml` v2 schema.

## Execution scheduling (`execution_plan.yaml`)

The orchestrator materializes `execution_plan.yaml` from `plan.yaml` execution groups. This file drives the coder's task ordering.

- Execution scheduling is strict: `execution_plan.yaml` must exist before implementation starts.
- Each group has a unique `group_id` and an execution mode (`serial` or `parallel`).
- `serial` groups execute plans one at a time in order.
- `parallel` groups execute all plans simultaneously.
- Plan entries use a YAML mapping with `file` and `name` keys, e.g. `- file: plan_1.md` with `name: Core setup`.

## Transitions

| From | Event | To |
|------|-------|----|
| `architecting` | `architecture_written` | `planning` |
| `planning` | `plan_written` (on `plan.yaml` submitted) | `designing` or `implementing` |

## Notes

- `execution_plan.yaml` must exist before implementation starts; the orchestrator materializes it from `plan.yaml` automatically.
- The `needs_design` flag in `plan.yaml` controls whether `designing` is inserted between planning and implementing.
- Research context from `03_research/` (if any) is injected into the planner prompt via `research_handoff`.
