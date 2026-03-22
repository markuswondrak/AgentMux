# Prompt Templates and Rendering

> Related source files: `src/prompts.py`, `src/prompts/agents/`, `src/prompts/commands/`

## Template directories

- `src/prompts/agents/` — role-level prompts (define what each agent is): `architect.md`, `product-manager.md`, `reviewer.md`, `coder.md`, `code-researcher.md`, `web-researcher.md`, `designer.md`
- `src/prompts/commands/` — phase-specific command prompts (what to do at each step): `review.md`, `fix.md`, `confirmation.md`, `change.md`, `docs.md`

## Placeholder syntax

Placeholders use `{name}` syntax, rendered via `str.format_map`.

Every template receives `{feature_dir}` as the session directory and references workflow files with phase subpaths (for example `planning/plan.md`, `review/review.md`, `state.json`).
Templates that need project-level context (for example product manager and coder) also receive `{project_dir}`.

## Prompt injection

Prompts are not injected as full text. Instead, `send_prompt()` in `src/tmux.py` sends a concise file reference message like:

```
Read and follow the instructions in /full/path/to/prompt_file.md
```

Agents read the referenced file themselves, reducing keystroke overhead and allowing agents to reuse file content without re-transmission. All prompt templates use file references (e.g., `requirements.md`, `planning/plan.md`) — agents fetch what they need.

## Lazy build

Prompt files are built lazily by handlers just before injection, not pre-generated. Each `build_*_prompt()` function in `src/prompts.py` loads and renders the markdown template for its phase.

Current split:
- `build_architect_prompt()` renders planning prompts only
- `build_product_manager_prompt()` renders the PM analysis prompt
- `build_reviewer_prompt(..., is_review=True)` renders the review command prompt
- `build_confirmation_prompt()` renders the confirmation command prompt used in completion
