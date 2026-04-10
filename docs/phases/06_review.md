# Phase: Review

> Directory: `06_review/` | Optional: no

The reviewer evaluates the implementation against the plan, producing a structured verdict. AgentMux routes to a specialized reviewer type based on the plan's `review_strategy`.

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

| Condition | Reviewer prompt used |
|-----------|---------------------|
| No `review_strategy` in plan | `review_logic_prompt.md` (backward-compatible default) |
| `severity: low` | `review_quality_prompt.md` |
| `severity: medium/high`, no security/performance focus | `review_logic_prompt.md` |
| `severity: medium/high` with `security` or `performance` in focus | `review_expert_prompt.md` |

## `review.yaml` schema

| Field | Required | Values |
|-------|----------|--------|
| `verdict` | yes | `"pass"` or `"fail"` |
| `summary` | yes | string |
| `findings` | on `fail` | list of `{location, issue, severity, recommendation}` |
| `commit_message` | optional on `pass` | string |
| `preferences` | optional | preferences written to agent prompt file under `## Approved Preferences` |

See [Handoff Contracts](../handoff-contracts.md#review) for full validation rules.

## Transitions

| From | Event | To |
|------|-------|----|
| `implementing` or `fixing` | `implementation_completed` | `reviewing` |
| `reviewing` | `review_passed` (verdict: pass) | `completing` |
| `reviewing` | `review_failed` (verdict: fail, below loop cap) | `fixing` |
| `reviewing` | `review_failed` (verdict: fail, loop cap reached) | `completing` |
