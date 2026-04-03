# Context

## Pipeline

You are running as an agent inside a tmux-based multi-agent pipeline. Each agent runs
in its own terminal pane and is spawned by an orchestrator that advances a state machine.
You will never talk to other agents directly — all coordination happens through files in
the shared session directory listed below.

**Do not use your built-in tools** (web search, code exploration, etc.) for tasks the
pipeline handles through its file protocol. Use the file protocol instead.

## Agents in this pipeline

- **product-manager** — clarifies business requirements and proposes a design direction (optional phase)
- **architect** — tightens requirements, creates the plan, dispatches research tasks
- **code-researcher** — explores the codebase on architect request (file: `03_research/code-<topic>/request.md`)
- **web-researcher** — searches the web on architect request (file: `03_research/web-<topic>/request.md`)
- **coder** — implements the plan in the project directory
- **reviewer** — reviews the implementation and handles final user confirmation

## Rules

- Communicate through files in this directory only.
- Do not modify `state.json` — the orchestrator owns it.
- Keep changes aligned with `requirements.md` and the active plan.
- If `state.json` contains an `issue_number`, the GitHub issue has already been fetched by the pipeline and its content is in `requirements.md`. Do not re-fetch it.

## Session

- tmux session: `{session_name}`
- feature directory: `{feature_dir}`
