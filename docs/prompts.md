# Prompt Templates and Rendering

> Related source files: `agentmux/workflow/prompts.py`, `agentmux/runtime/tmux_control.py`, `agentmux/prompts/agents/`, `agentmux/prompts/commands/`

## Template directories

- `agentmux/prompts/agents/` — role-level prompts (define what each agent is): `architect.md`, `product-manager.md`, `reviewer.md`, `coder.md`, `code-researcher.md`, `web-researcher.md`, `designer.md`
- `agentmux/prompts/commands/` — phase-specific command prompts (what to do at each step): `review.md`, `fix.md`, `confirmation.md`, `change.md`, `docs.md`

## Placeholder syntax

Placeholders use `{name}` syntax, rendered via `str.format_map`.

Every template receives `{feature_dir}` as the session directory and references workflow files with phase subpaths (for example `02_planning/plan.md`, `06_review/review.md`, `state.json`).
Templates that need project-level context (for example product manager and coder) also receive `{project_dir}`.
All built-in agent and command templates also include a `{project_instructions}` injection point.

## Project-specific prompt extensions

Projects can extend built-in prompt templates with plain markdown files in:

- `.agentmux/prompts/agents/<role>.md`
- `.agentmux/prompts/commands/<command>.md`

The prompt loader merges project content into the matching built-in template via `{project_instructions}`.
If a project file does not exist, `{project_instructions}` resolves to an empty string and behavior stays unchanged.

Project extension files are plain markdown. They do not need template placeholder syntax.
Curly braces in project content are automatically escaped before `format_map()` runs, so text like `{example}` is preserved literally and cannot trigger placeholder errors.

`agentmux/prompts/context.md` is pipeline-controlled and is not project-extendable.

## Prompt injection

Prompts are not injected as full text. Instead, `send_prompt()` in `agentmux/runtime/tmux_control.py` sends a concise file reference message like:

```
Read and follow the instructions in /full/path/to/prompt_file.md
```

Agents read the referenced file themselves, reducing keystroke overhead and allowing agents to reuse file content without re-transmission. All prompt templates use file references (e.g., `requirements.md`, `02_planning/plan.md`) — agents fetch what they need.

## Lazy build

Prompt files are built lazily by handlers just before injection, not pre-generated. Each `build_*_prompt()` function in `agentmux/workflow/prompts.py` loads and renders the markdown template for its phase.

## Coder research handoff

Coder prompt rendering injects a `Research handoff` block into `agentmux/prompts/agents/coder.md` via the `{research_handoff}` placeholder.

Behavior contract:

- Applies to both `build_coder_prompt()` and `build_coder_subplan_prompt()`
- Scans topic directories under `03_research/` in sorted (deterministic) order
- Includes a topic only when both `done` and `summary.md` are present
- Lists `summary.md` as the primary reference
- Adds `detail.md` as an additional reference only when present
- Uses feature-relative paths (for example `03_research/code-auth/summary.md`)
- Omits the entire handoff section when no completed research topics are available

## Staged planning contract

Planning and replanning prompts share one contract for implementation scheduling artifacts:

- `02_planning/plan.md` is the human-readable overview
- `02_planning/plan_<N>.md` files are executable implementation units
- `02_planning/execution_plan.json` is the scheduling source of truth (ordered execution groups, each marked as `serial` or `parallel`, with explicit named plan references)
- `02_planning/tasks.md` remains the implementation checklist mapped to the same work
- `02_planning/plan_meta.json` remains workflow intent metadata (`needs_design`, `needs_docs`, `doc_files`)

Architect output requirements for parallel work include:

- A Phase 1 / Phase 2 / Phase 3 breakdown where Phase 1 defines interfaces/contracts and Phase 2 uses those contracts for parallel implementation
- Per parallel sub-plan sections for `Scope`, `Dependencies`, and `Isolation`
- Explicit conflict mapping by touched files; empty file-set intersection should be treated as parallelizable unless a precise technical conflict is documented
- A callout for any enabling refactor needed to preserve boundaries, plus explicit technical debt rationale when refactor work is deferred

Compatibility requirement:

- Keep `## Sub-plan <N>: <title>` headers in `plan.md` so legacy split-based workflows and tooling remain operable during migration.

Current split:
- `build_architect_prompt()` renders planning prompts only
- `build_change_prompt()` applies the same staged planning artifact contract in replanning mode
- planning/replanning prompt contracts require:
  - `02_planning/plan.md` as the human-readable overview
  - `02_planning/plan_<N>.md` executable sub-plan files
  - `02_planning/execution_plan.json` as machine-readable schedule metadata (`version`, ordered `groups`, `group_id`, `mode`, `plans`)
  - new plans must write `groups[].plans[]` entries as `{ "file": "plan_<N>.md", "name": "<sub-plan title>" }`
  - `02_planning/plan_meta.json` with `needs_design`, `needs_docs`, and `doc_files` (empty list when `needs_docs` is `false`)
  - compatibility behavior where legacy flat `plan.md` parsing is only a fallback when `execution_plan.json` is absent
- `build_product_manager_prompt()` renders the PM analysis prompt
- `build_coder_prompt()` / `build_coder_subplan_prompt()` render coder implementation prompts with completion marker instructions and optional research handoff references
- `build_reviewer_prompt(..., is_review=True)` renders the review command prompt
- `build_docs_prompt()` requires `02_planning/plan_meta.json` with `needs_docs: true` and a non-empty `doc_files` list, then injects those file paths as the only docs-update scope
- `build_confirmation_prompt()` renders the confirmation command prompt used in completion
