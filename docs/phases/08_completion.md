# Phase: Completion

> Related source file: `src/agentmux/workflow/handlers/completing.py`
> Directory: `08_completion/` | Optional: no

The reviewer writes a human-readable summary of the implementation. The pipeline then awaits user approval or a change request via the native completion UI.

## Conditions

Entered from `reviewing` when the review passes (`review_passed` event) or when the review loop cap is reached.

## Role

**reviewer** agent — writes `summary.md` while still in the `reviewing` phase (with `awaiting_summary: true` in `state.json`). After the summary is written, the pipeline transitions to `completing` and the **completion UI** takes over (native terminal TUI or auto-approval depending on config).

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `summary_prompt.md` | orchestrator | reviewer agent | Markdown prompt |
| `summary.md` | reviewer agent | PR description, humans | Markdown |
| `approval.json` | completion UI (user approves) | orchestrator | JSON |
| `changes.md` | completion UI (user requests changes) | orchestrator | Markdown |

## Transitions

| From | Event | To |
|------|-------|----|
| `reviewing` (pass or loop cap) | `review_passed` / `review_failed` | `completing` |
| `completing` | `approval_received` (on `approval.json`) | `done` (pipeline ends) |
| `completing` | `changes_requested` (on `changes.md`) | `architecting` (re-planning) |

## Flow

1. **Summary written** — The reviewing handler sends `summary_prompt.md` to the reviewer (while still in `reviewing` with `awaiting_summary: true`). When `summary.md` appears, the reviewer pane is killed and `completing` is entered.

2. **Completion mode** — Controlled by `workflow_settings.completion.skip_final_approval`:
   - `false` (default): native terminal UI is launched in the tmux content zone.
   - `true`: auto-approval writes `approval.json` with `{"action": "approve", "exclude_files": []}`.

3. **Native UI** — Displays the summary, changed file count, and a `[Y] / [N]` panel. `Y` writes `approval.json`; `N` prompts for feedback and writes `changes.md`. `/cancel` or `Ctrl+C` returns to the panel.

4. **Commit + PR** — On approval, the pipeline stages changed files, commits, and optionally creates a GitHub branch + PR if `gh` is available. The feature directory is deleted only on a successful commit.

5. **Post-completion artifact** — On success, writes `<project_dir>/.agentmux/.last_completion.json` before cleanup so the goodbye screen can display commit and PR info.

See [Artifact: completion-artifacts.md](../artifacts/completion-artifacts.md) for full schemas of `approval.json`, `changes.md`, and `.last_completion.json`.

## Notes

- When the user approves, the pipeline commits locally and optionally opens a draft PR if `gh` is available and configured.
- When the user requests changes, the architect receives a re-planning prompt with the description from `changes.md` and the cycle restarts.
- GitHub branch/PR failures do not roll back the local commit.
- Reviewer-stage preferences (via `submit_review` tool's `preferences` parameter) are written to `.agentmux/prompts/agents/<role>.md` under `## Approved Preferences`.
- **Worktree mode** — When the session was started with `--worktree`, `last_completion.json` is written to the main repository (`main_repo_dir` from `state.json`) rather than the worktree, so it is always accessible after the worktree is removed.  The worktree is registered in the `ExitStack` *after* the feature-directory cleanup entry, so LIFO teardown removes the feature directory first and the worktree second.
