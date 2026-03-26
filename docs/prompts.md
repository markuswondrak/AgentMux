# Prompt Templates and Rendering

> Related source files: `agentmux/prompts.py`, `agentmux/prompts/agents/`, `agentmux/prompts/commands/`

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

Prompts are not injected as full text. Instead, `send_prompt()` in `agentmux/tmux.py` sends a concise file reference message like:

```
Read and follow the instructions in /full/path/to/prompt_file.md
```

Agents read the referenced file themselves, reducing keystroke overhead and allowing agents to reuse file content without re-transmission. All prompt templates use file references (e.g., `requirements.md`, `02_planning/plan.md`) — agents fetch what they need.

## Lazy build

Prompt files are built lazily by handlers just before injection, not pre-generated. Each `build_*_prompt()` function in `agentmux/prompts.py` loads and renders the markdown template for its phase.

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

Current split:
- `build_architect_prompt()` renders planning prompts only
- planning/replanning prompt contracts require `02_planning/plan_meta.json` with `needs_design`, `needs_docs`, and `doc_files` (empty list when `needs_docs` is `false`)
- `build_product_manager_prompt()` renders the PM analysis prompt
- `build_coder_prompt()` / `build_coder_subplan_prompt()` render coder implementation prompts with completion marker instructions and optional research handoff references
- `build_reviewer_prompt(..., is_review=True)` renders the review command prompt
- `build_docs_prompt()` requires `02_planning/plan_meta.json` with `needs_docs: true` and a non-empty `doc_files` list, then injects those file paths as the only docs-update scope
- `build_confirmation_prompt()` renders the confirmation command prompt used in completion
