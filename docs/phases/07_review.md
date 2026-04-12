# Phase: Review

> Related source files: `src/agentmux/workflow/handlers/reviewing.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/prompts.py`, `src/agentmux/integrations/mcp_server.py`
> Directory: `07_review/` | Optional: no

The reviewer evaluates the implementation against the plan, producing a structured verdict. AgentMux routes to a specialized reviewer type based on the plan's `review_strategy`.

## Conditions

Entered after `implementing` or `fixing` completes (`implementation_completed` event).

## Role

One of four reviewer agents is selected based on `review_strategy.severity` and `review_strategy.focus` from `plan.yaml`:

| Condition | Agent used |
|-----------|------------|
| No `review_strategy` in plan | **reviewer_logic** (backward-compatible default) |
| `severity: low` | **reviewer_quality** |
| `severity: medium/high`, no security/performance focus | **reviewer_logic** |
| `severity: medium/high` with `security` or `performance` in focus | **reviewer_expert** |

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `review_prompt.md` | orchestrator (legacy fallback) | reviewer agent | Markdown prompt |
| `review_logic_prompt.md` | orchestrator | Logic & Alignment reviewer | Markdown prompt |
| `review_quality_prompt.md` | orchestrator | Quality & Style reviewer | Markdown prompt |
| `review_expert_prompt.md` | orchestrator | Deep-Dive Expert reviewer | Markdown prompt |
| `review.yaml` | reviewer agent (via `submit_review`) | orchestrator | YAML |
| `review.md` | reviewer agent or orchestrator (auto-generated from `review.yaml`) | summary, monitor, PR | Markdown |
| `fix_prompt.md` | orchestrator | coder agent (fixing phase) | Markdown |
| `fix_request.md` | orchestrator | coder agent (fixing phase) | Markdown |

## Reviewer selection

See the **Role** section above for the routing table.

## `review.yaml` schema

See [Artifact: review.yaml](../artifacts/review-yaml.md) for the full schema and field-level documentation.

**Summary of fields:**

| Field | Required | Values |
|-------|----------|--------|
| `verdict` | yes | `"pass"` or `"fail"` |
| `summary` | yes | string |
| `findings` | on `fail` | list of `{location, issue, severity, recommendation}` |
| `commit_message` | optional | string (used verbatim as commit message on pass) |

## Transitions

| From | Event | To |
|------|-------|----|
| `implementing` or `fixing` | `implementation_completed` | `reviewing` |
| `reviewing` | `review_passed` (verdict: pass) | `completing` |
| `reviewing` | `review_failed` (verdict: fail, below loop cap) | `fixing` |
| `reviewing` | `review_failed` (verdict: fail, loop cap reached) | `completing` |

## Notes

- If `review.md` is missing when downstream prompts need it, AgentMux materializes it automatically from `review.yaml`.
- The reviewer also writes `08_completion/summary.md` after a pass verdict (while still in `reviewing` phase with `awaiting_summary: true` in state), before the pipeline transitions to `completing`.
- See [Handoff Contracts](../handoff-contracts.md#review) for full validation rules applied to `review.yaml`.
