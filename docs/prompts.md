# Prompt Templates and Rendering

> Related source files: `agentmux/workflow/prompts.py`, `agentmux/runtime/tmux_control.py`, `agentmux/prompts/agents/`, `agentmux/prompts/commands/`

## Template directories

- `agentmux/prompts/agents/` — role-level prompts (define what each agent is): `architect.md`, `planner.md`, `product-manager.md`, `reviewer.md`, `coder.md`, `code-researcher.md`, `web-researcher.md`, `designer.md`
- `agentmux/prompts/commands/` — phase-specific command prompts (what to do at each step): `review.md`, `review_logic.md`, `review_quality.md`, `review_expert.md`, `fix.md`, `summary.md`, `change.md`

## Placeholder syntax

Built-in prompt templates use `[[placeholder:name]]` value placeholders.
Built-in templates can also inline session files with:

- `[[include:path]]` — required include; raises `FileNotFoundError` when missing.
- `[[include-optional:path]]` — optional include; resolves to empty string when missing.

Render model is three-stage:

1. Template loading stage:
   - Expand shared fragments using `[[shared:fragment-name]]`.
   - Inject project extension text into `[[placeholder:project_instructions]]`.
2. Render stage:
   - Resolve `[[placeholder:name]]` values from the active prompt builder context.
3. Session include expansion stage:
   - Resolve `[[include:path]]` / `[[include-optional:path]]` against `feature_dir`.
   - Include expansion runs after placeholder rendering, so include paths can contain placeholders (for example `[[include:[[placeholder:plan_file]]]]`).

Every prompt builder provides `feature_dir` as the session directory and references workflow files with phase subpaths (for example `02_planning/plan.md`, `06_review/review.md`, `state.json`).
Builders that need project-level context (for example product manager and coder) also provide `project_dir`.

## Project-specific prompt extensions

Projects can extend built-in prompt templates with plain markdown files in:

- `.agentmux/prompts/agents/<role>.md`
- `.agentmux/prompts/commands/<command>.md`

The prompt loader merges project content into the matching built-in template via `[[placeholder:project_instructions]]`.
If a project file does not exist, `[[placeholder:project_instructions]]` resolves to an empty string and behavior stays unchanged.

Project extension files are plain markdown. They do not need template placeholder syntax.
Curly braces in project content stay literal; only `[[placeholder:...]]` markers are rendered.

`agentmux/prompts/context.md` is pipeline-controlled and is not project-extendable.

## Preference memory artifacts

Preference memory uses session-scoped proposal artifacts so agents never mutate project extensions directly:

- `01_product_management/approved_preferences.json` (product-manager approvals)
- `02_planning/approved_preferences.json` (architect and planner approvals)
- `08_completion/approved_preferences.json` (reviewer approvals)

Each proposal uses this shape:

```json
{
  "source_role": "product-manager|architect|planner|reviewer",
  "approved": [
    {"target_role": "coder", "bullet": "- ..."}
  ]
}
```

Application flow:

- Agents write proposal artifacts only after explicit user approval.
- The orchestrator applies proposals during phase transitions (`pm_completed`, `plan_written`, `approval_received`).
- Applied preferences are appended to `.agentmux/prompts/agents/<role>.md`.
- Prompt builds are lazy, so newly persisted preferences are visible in subsequent prompt renders in later phases.

Deduplication rules (high level):

- Normalize bullets by trimming, removing leading bullet markers (`-`, `*`, `+`), collapsing whitespace, and comparing case-insensitively.
- Deduplicate within the current proposal batch per target role.
- Skip appending bullets already present in the target extension file after normalization.

## Prompt injection

Prompts are not injected as full text. Instead, `send_prompt()` in `agentmux/runtime/tmux_control.py` sends a concise file reference message like:

```
Read and follow the instructions in /full/path/to/prompt_file.md
```

Agents still read the referenced prompt file themselves. Prompt files are now self-contained: session files referenced by template includes are inlined at build time, so agents do not need extra tool calls to fetch `requirements.md`, `plan.md`, `state.json`, and similar inputs separately.

## Lazy build

Prompt files are built lazily by handlers just before injection, not pre-generated. Each `build_*_prompt()` function in `agentmux/workflow/prompts.py` loads and renders the markdown template for its phase.

Startup and resume now use explicit phase bootstrap: the orchestrator re-enters the active phase before steady-state event sources start, and that phase entry is what causes the handler to build and send the current prompt. Prompt injection therefore does not depend on the first seeded `file.created` event.

## Coder research handoff

Coder prompt rendering injects a `Research handoff` block into `agentmux/prompts/agents/coder.md` via `[[placeholder:research_handoff]]`.

Behavior contract:

- Applies to `build_coder_subplan_prompt()`
- Scans topic directories under `03_research/` in sorted (deterministic) order
- Includes a topic only when both `done` and `summary.md` are present
- Lists `summary.md` as the primary reference
- Adds `detail.md` as an additional reference only when present
- Uses feature-relative paths (for example `03_research/code-auth/summary.md`)
- Omits the entire handoff section when no completed research topics are available

## Coder workflow contract

The coder prompt contract now requires:

- TDD protocol: write tests first, run them, verify they fail (Red), then implement until tests pass (Green).
- Strict phase order discipline: follow the active plan/sub-plan phase order and do not move to later-phase logic early.
- Atomic execution from tasks: complete one task from your assigned `02_planning/tasks_<N>.md` at a time, validate it, and check it off before starting the next task.
- Completion marker flow remains unchanged: finish all required validation first, then create the phase completion marker as the final action.

## Staged planning contract

The architect/planner split is:

- **Architect** (`build_architect_prompt()`) — defines the technical design: solution approach, components, interfaces, data models, cross-cutting concerns, technology choices, risks. Sole output: `02_planning/architecture.md`.
- **Planner** (`build_planner_prompt()`) — receives `architecture.md` and produces the full execution schedule. Sole owner of all plan files.

Planner (and replanning via `build_change_prompt()`) output contract:

- `02_planning/plan.md` is the human-readable overview
- `02_planning/plan_<N>.md` files are executable implementation units
- `02_planning/execution_plan.json` is the scheduling source of truth (ordered execution groups, each marked as `serial` or `parallel`, with explicit named plan references)
- `02_planning/tasks_<N>.md` are per-plan implementation checklists mapped to the same work; each coder receives only their assigned plan's tasks
- `02_planning/tasks.md` is an optional human-readable overview summarizing all tasks (not used by scheduler)
- `02_planning/plan_meta.json` is planner workflow-intent metadata (`needs_design`, `needs_docs`, `doc_files`, `review_strategy`)
- Documentation updates must be represented in planning artifacts (`plan.md`, `plan_<N>.md`, and corresponding `tasks_<N>.md`) rather than a dedicated post-review docs phase.

Planner output requirements for execution plans include:

- A Phase 1 / Phase 2 / Phase 3 breakdown where Phase 1 defines interfaces/contracts and Phase 2 uses those contracts for parallel implementation
- Per parallel sub-plan sections for `Scope`, `Owned files/modules`, `Dependencies`, and `Isolation`
- Explicit conflict mapping by touched files/modules plus explicit ownership for each parallel lane
- Safety-first rule: Phase 2 parallel sub-plans are allowed only when their owned files/modules are disjoint; if two lanes would edit the same file/module, that work must be merged into one sub-plan or moved into a serial integration step
- Shared mutable artifacts such as `02_planning/tasks.md`, prompt templates, monitor/state metadata files, and cross-cutting tests/docs should have a single Phase 2 owner unless intentionally deferred to integration
- `Isolation` must be justified in terms of exclusive ownership, not only logical separation
- A callout for any enabling refactor needed to preserve boundaries, plus explicit technical debt rationale when refactor work is deferred

Current prompt builders:
- `build_architect_prompt()` renders architecting prompts (creates `architecture.md`)
- `build_planner_prompt()` renders planning prompts (creates plan files from `architecture.md`)
- `build_change_prompt()` applies the same staged planning artifact contract in replanning mode
- planning/replanning prompt contracts require:
  - `02_planning/plan.md` as the human-readable overview
  - `02_planning/plan_<N>.md` executable sub-plan files
  - `02_planning/execution_plan.json` as machine-readable schedule metadata (`version`, ordered `groups`, `group_id`, `mode`, `plans`)
  - new plans must write `groups[].plans[]` entries as `{ "file": "plan_<N>.md", "name": "<sub-plan title>" }`
  - `02_planning/plan_meta.json` with `needs_design`, `needs_docs`, and `doc_files` (empty list when `needs_docs` is `false`)
  - `execution_plan.json` is required before implementation scheduling starts
- `build_product_manager_prompt()` renders the PM analysis prompt
- `build_coder_subplan_prompt()` renders implementing prompts for numbered `coder_prompt_<N>.txt` dispatch, including completion marker instructions and optional research handoff references
- `build_reviewer_prompt(..., is_review=True)` renders the review command prompt
- `build_reviewer_summary_prompt()` renders the reviewer summary prompt (writes `08_completion/summary.md` after VERDICT:PASS)
