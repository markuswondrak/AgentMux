# Handoff Contracts

> Related source files: `agentmux/workflow/handoff_contracts.py`, `agentmux/workflow/handoff_artifacts.py`, `agentmux/integrations/mcp_server.py`, `agentmux/prompts/shared/handoff-contract-architecture.md`, `agentmux/prompts/shared/handoff-contract-plan.md`, `agentmux/prompts/shared/handoff-contract-review.md`

Handoff contracts define the structured interface between workflow phases. Each contract specifies the fields an agent must produce, validates submissions, and drives the orchestrator to materialize derived artifacts.

## Overview

Agents submit phase outputs by writing the canonical file, then calling the MCP submission tool as a completion signal:

1. **Write the output file** — the agent writes the artifact directly (e.g., `02_planning/architecture.md`, `02_planning/plan.yaml`). Shared prompt fragments (`[[shared:handoff-contract-*]]`) embedded in agent prompts provide the schema and examples.
2. **Call the MCP signal tool** — the `agentmux-research` MCP server exposes `submit_*` tools that validate the agent-written file, append a minimal signal entry to `tool_events.jsonl`, and return a confirmation string (or a validation error the agent can act on). The tools write no files themselves.

The orchestrator observes the signal event, materializes derived companions and scheduling files, and drives the state transition.

Completion semantics are phase-specific:

- **Architecture** — the architect writes `architecture.md` directly. No YAML is produced; the planner consumes the Markdown file directly.
- **Plan** — the planner writes one `plan.yaml` (version 2) containing all sub-plans and execution metadata. The orchestrator materializes `plan_N.md`, `tasks_N.md`, `execution_plan.yaml`, and `plan.md` automatically.
- **Review** — `review.yaml` is the canonical structured review artifact. If `review.md` is missing, AgentMux materializes it from `review.yaml` before summary/completion steps so downstream prompts can continue to read the Markdown companion.

## Contracts

### Architecture

- **MCP tool:** `submit_architecture`
- **Artifacts:** see [phases/planning.md § Architecting](phases/planning.md#architecting)
- **Validation:** `architecture.md` must be non-empty

### Plan

- **MCP tool:** `submit_plan`
- **Artifacts:** see [phases/planning.md § Planning](phases/planning.md#planning)
- **Required fields:** `version` (must be `2`), `plan_overview`, `groups`, `subplans`, `review_strategy`, `needs_design`, `needs_docs`, `doc_files`

`plan.yaml` schema (version 2):
```yaml
version: 2
plan_overview: |
  Human-readable overview…
review_strategy:
  severity: medium   # low | medium | high
  focus: [security]
needs_design: false
needs_docs: true
doc_files: [docs/api.md]
groups:
  - group_id: core-setup
    mode: serial     # serial | parallel
    plans:
      - index: 1
        name: Core setup
subplans:
  - index: 1
    title: Short descriptive title
    scope: What this sub-plan covers
    owned_files: [src/auth.py]
    dependencies: None
    implementation_approach: |
      Step-by-step approach.
    acceptance_criteria: |
      Testable criteria for completion.
    tasks:
      - First task
    isolation_rationale: |   # optional
      Why safe for parallel execution.
```

Groups reference sub-plans by `index`. Indices must start at 1 and be contiguous (1, 2, 3, …). The orchestrator converts `{index: N, name: "..."}` → `{file: plan_N.md, name: "..."}` when materializing `execution_plan.yaml`.

### Review

- **MCP tool:** `submit_review`
- **Artifacts:** see [phases/review.md](phases/review.md)
- **Required fields:** `verdict` (`"pass"` or `"fail"`), `summary`
- **Conditional fields:** `findings` (required on `fail` — list of `{location, issue, severity, recommendation}`), `commit_message` (optional on `pass`)

## Preference persistence via submit tool parameter

All four submit tools (`submit_architecture`, `submit_pm_done`, `submit_plan`, `submit_review`) accept an optional `preferences` parameter:

```python
submit_review(
    preferences=[
        {"target_role": "coder", "bullet": "- Keep regression tests"}
    ]
)
```

When provided, the MCP server calls `apply_preference_entries(project_dir, preferences)` which appends bullets to `.agentmux/prompts/agents/<role>.md` under `## Approved Preferences` — creating the section and file if absent. Deduplication is applied on a normalized casefold basis. The `preferences` parameter is independent of the YAML artifacts; it is a direct tool call argument, not a YAML field.

`validate_submission(contract_name, data)` in `handoff_contracts.py` performs:

1. **Required-field presence** — all required fields must be present
2. **Type checking** — loose type validation against field specs (`str`, `bool`, `int`, `list[str]`, `list[dict]`, `dict`)
3. **Allowed-value enforcement** — fields with constrained values (e.g., verdict: `pass`/`fail`) are validated
4. **Contract-specific rules:**
   - Plan: `version` must be `2`; groups non-empty with unique `group_id` and valid `mode`; subplans non-empty with required string fields, non-empty `tasks` and `owned_files`, contiguous `index` values starting at 1
   - Review: `fail` verdict requires non-empty `findings` with `issue` and `recommendation`

MCP tools raise a validation error with all issues listed; agents receive the error message and can correct their submission.

## Shared prompt fragments

Three shared fragments provide agents with file-writing instructions and YAML schema examples:

| Fragment | Included by | Purpose |
|---|---|---|
| `handoff-contract-architecture.md` | `architect.md` | Architecture submission instructions |
| `handoff-contract-plan.md` | `planner.md`, `change.md` | Plan submission instructions (plan.yaml v2) |
| `handoff-contract-review.md` | `review_logic.md`, `review_quality.md`, `review_expert.md` | Review submission instructions |

These are inlined at template-load time via the `[[shared:fragment-name]]` syntax.
