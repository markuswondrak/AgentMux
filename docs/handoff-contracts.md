# Handoff Contracts

> Related source files: `agentmux/workflow/handoff_contracts.py`, `agentmux/workflow/handoff_artifacts.py`, `agentmux/integrations/mcp_research_server.py`, `agentmux/prompts/shared/handoff-contract-architecture.md`, `agentmux/prompts/shared/handoff-contract-plan.md`, `agentmux/prompts/shared/handoff-contract-review.md`

Handoff contracts define the structured interface between workflow phases. Each contract specifies the fields an agent must produce, validates submissions, and writes dual output files (YAML canonical + MD human-readable).

## Overview

Agents submit phase outputs through either:

1. **MCP submission tools** (preferred) — the `agentmux-research` MCP server exposes four `agentmux_submit_*` tools that accept structured parameters, validate them against the contract, and write both `.yaml` and `.md` files.
2. **Direct YAML write** (fallback) — agents that cannot call MCP tools write the canonical `.yaml` file directly. Shared prompt fragments (`[[shared:handoff-contract-*]]`) embedded in agent prompts provide the YAML schema and examples.

Completion semantics are phase-specific:

- **Architecture** — `architecture.yaml` is the canonical structured artifact, but the planner prompt still consumes `architecture.md`, so the companion Markdown file remains required in practice.
- **Execution plan + subplans** — `execution_plan.yaml` / `plan_N.yaml` are canonical structured artifacts, but `plan.md`, `plan_N.md`, and `tasks_N.md` remain required human-readable companions for downstream prompts and coder handoffs.
- **Review** — `review.yaml` is the canonical structured review artifact. If `review.md` is missing, AgentMux materializes it from `review.yaml` before summary/completion steps so downstream prompts can continue to read the Markdown companion.

## Contracts

### Architecture

- **MCP tool:** `agentmux_submit_architecture`
- **Canonical file:** `02_planning/architecture.yaml`
- **Companion file:** `02_planning/architecture.md`
- **Required fields:** `solution_overview`, `components` (list of `{name, responsibility, interfaces}`), `interfaces_and_contracts`, `data_models`, `cross_cutting_concerns`, `technology_choices`, `risks_and_mitigations`
- **Optional fields:** `design_handoff`

### Execution plan

- **MCP tool:** `agentmux_submit_execution_plan`
- **Canonical file:** `02_planning/execution_plan.yaml`
- **Companion file:** `02_planning/plan.md`
- **Required fields:** `groups` (list of `{group_id, mode, plans: [{file, name}]}`), `review_strategy` (`{severity, focus}`), `needs_design`, `needs_docs`, `doc_files`, `plan_overview`

The YAML file merges the former `execution_plan.json` scheduling data and `plan_meta.json` workflow-intent metadata into a single file with a `version: 1` header.

### Subplan

- **MCP tool:** `agentmux_submit_subplan`
- **Canonical file:** `02_planning/plan_N.yaml`
- **Companion files:** `02_planning/plan_N.md`, `02_planning/tasks_N.md`
- **Required fields:** `index`, `title`, `scope`, `owned_files`, `dependencies`, `implementation_approach`, `acceptance_criteria`, `tasks`
- **Optional fields:** `isolation_rationale`

Subplans are submitted individually before the execution plan. The `index` value determines the `N` in file names.

### Review

- **MCP tool:** `agentmux_submit_review`
- **Canonical file:** `06_review/review.yaml`
- **Companion file:** `06_review/review.md`
- **Required fields:** `verdict` (`"pass"` or `"fail"`), `summary`
- **Conditional fields:** `findings` (required on `fail` — list of `{location, issue, severity, recommendation}`), `commit_message` (optional on `pass`)

## Validation

`validate_submission(contract_name, data)` in `handoff_contracts.py` performs:

1. **Required-field presence** — all required fields must be present
2. **Type checking** — loose type validation against field specs (`str`, `bool`, `int`, `list[str]`, `list[dict]`, `dict`)
3. **Allowed-value enforcement** — fields with constrained values (e.g., verdict: `pass`/`fail`) are validated
4. **Contract-specific rules:**
   - Architecture: each component must have `name` and `responsibility`
   - Execution plan: groups must be non-empty, unique `group_id`, valid `mode`, plans must have `file` and `name`
   - Subplan: `index` >= 1, non-empty `tasks` and `owned_files`
   - Review: `fail` verdict requires non-empty `findings` with `issue` and `recommendation`

MCP tools raise a validation error with all issues listed; agents receive the error message and can correct their submission.

## Dual-file output

Each submission writes two files:

- **`.yaml`** — the machine-readable canonical artifact.
- **`.md`** — a human-readable companion generated from the same data. Useful for attaching to tmux, reviewing in PRs, and reading in subsequent agent prompts via `[[include:...]]`.

For architecture, execution plans, and subplans, the `.md` companions are still required by downstream prompts. For reviews, the runtime can synthesize `review.md` from `review.yaml` when the Markdown companion is missing.

## Shared prompt fragments

Three shared fragments provide agents with MCP tool usage instructions and YAML fallback examples:

| Fragment | Included by | Purpose |
|---|---|---|
| `handoff-contract-architecture.md` | `architect.md` | Architecture submission instructions |
| `handoff-contract-plan.md` | `planner.md`, `change.md` | Execution plan + subplan submission instructions |
| `handoff-contract-review.md` | `review_logic.md`, `review_quality.md`, `review_expert.md` | Review submission instructions |

These are inlined at template-load time via the `[[shared:fragment-name]]` syntax.
