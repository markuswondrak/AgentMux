# Shared File Protocol

> Related source files: `agentmux/models.py`, `agentmux/state.py`, `agentmux/phases.py`, `agentmux/handlers.py`

Agents communicate via files in `.multi-agent/<feature-name>/`. Files are grouped by phase subdirectories and created on-demand as needed.

## Root files

- `state.json` — current workflow phase; orchestrator drives transitions
- `requirements.md` — initial request passed to architect
- `context.md` — auto-generated rules/session info injected into prompts
- `runtime_state.json` / `orchestrator.log` — runtime tracking and orchestrator logs

## Product Management (`product_management/`)

- `product_manager_prompt.md` — prompt for PM analysis phase
- `analysis.md` — PM write-up (business case, integration assessment, alternatives)
- `done` — completion marker for PM handoff to planning

## Planning (`planning/`)

- `architect_prompt.md` / `changes_prompt.txt` — architect prompts
- `plan.md` / `tasks.md` / `plan_meta.json` — architect planning artifacts
- `plan_*.md` — subplan files for parallel coder runs

## Research (`research/`)

- `code-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`
- `web-<topic>/request.md` / `summary.md` / `detail.md` / `done` / `prompt.md`

## Design (`design/`)

- `designer_prompt.md` / `design.md`

## Implementation (`implementation/`)

- `coder_prompt.md` / `coder_prompt_*.txt`
- `done_*` — coder completion markers for single or parallel implementation/fixing

## Review (`review/`)

- `review_prompt.md` / `review.md`
- `fix_prompt.txt` / `fix_request.md`

## Docs (`docs/`)

- `docs_prompt.txt` / `docs_done`

## Completion (`completion/`)

- `confirmation_prompt.md` / `approval.json`
- `changes.md`

## Key functions

- `orchestrate()` in `agentmux/pipeline.py` — main file-watch loop; dispatches to role-specific handlers
- `build_initial_prompts()` in `agentmux/prompts.py` — builds only the architect prompt at startup
- `build_*_prompt()` in `agentmux/prompts.py` — loads and renders the markdown template for each phase; called lazily by handlers
- Handler functions in `agentmux/handlers.py` — each builds and writes its prompt file just before sending to agent
