# Phase: Review

> Related source files: `src/agentmux/workflow/handlers/reviewing.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/prompts.py`, `src/agentmux/integrations/mcp_server.py`
> Directory: `07_review/` | Optional: no

The reviewer evaluates the implementation against the plan, producing a structured verdict. The architect nominates which reviewer roles should run via `submit_architecture(reviewers=[...])`.

## Conditions

Entered after `implementing` or `fixing` completes (`implementation_completed` event).

## Role

The architect nominates the reviewer set via `submit_architecture(reviewers=[...])` during the architecting phase. Valid values:

| Role | Purpose |
|------|---------|
| `reviewer_logic` | Checks alignment to plan and functional correctness |
| `reviewer_quality` | Checks code quality, style, and maintainability |
| `reviewer_expert` | Checks security, performance, and edge cases |

When `reviewers` is omitted or empty, only `reviewer_logic` runs by default.

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

The architect nominates the reviewer set via `submit_architecture(reviewers=[...])` during the architecting phase. The nominations are stored in `state["reviewer_nominations"]` and read by `select_reviewer_roles(state)` to determine which reviewer panes to dispatch.

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
- **Post-fix follow-up prompt**: When re-entering `reviewing` after a `fixing` iteration (`review_iteration > 0`) and the previous iteration's role-specific archive `review_{prev}_{pane_role}.md` exists, the handler dispatches a compact follow-up prompt built from `prompts/commands/review_followup.md` instead of the full initial prompt. It references only the reviewer's own prior archive and the aggregated `fix_request.md` — no `context.md`, `architecture.md`, or `plan.md` includes. If the archive is missing (e.g. the previous round was killed), the handler falls back to the initial prompt.
- See [Handoff Contracts](../handoff-contracts.md#review) for full validation rules applied to `review.yaml`.
