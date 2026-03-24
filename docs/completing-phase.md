# Completing Phase

> Related source files: `agentmux/phases.py` (CompletingPhase), `agentmux/prompts/commands/confirmation.md`, `agentmux/state.py`

When the review passes, the workflow first terminates all `coder` panes (primary and parallel workers), then enters the `documenting` phase (if docs updates are needed) and finally transitions to `completing`.

## Flow

1. **Confirmation prompt displays changed files** — The confirmation prompt shows all files detected by `git status --porcelain` from the project directory. This gives the architect full visibility into what will be committed.

2. **Architect specifies exclusions (not inclusions)** — Instead of manually enumerating files to commit, the architect simply lists any files to **exclude** from the commit in the `completion/approval.json` response. By default, an empty `exclude_files` list means commit all detected changes.

3. **`completion/approval.json` schema**:
   ```json
   {
     "action": "approve",
     "commit_message": "...",
     "exclude_files": []
   }
   ```

4. **Auto-detection and filtering** — The completing phase handler (`CompletingPhase.handle_event()`) reads git status again when processing the approval, removes any files listed in `exclude_files`, and passes the remaining file list to `commit_changes()`.

5. **Branch + PR creation (best effort)** — If startup state indicates GitHub is available (`gh_available: true`), the completing handler creates a branch (`<github.branch_prefix><feature-slug>`), pushes it, and runs `gh pr create` against `github.base_branch`. PRs default to draft (`github.draft: true`). The PR body is assembled from `requirements.md`, `planning/plan.md`, and `review/review.md`, and includes `Closes #<N>` when the run started with `--issue`.

6. **Cleanup only on success** — The feature directory is deleted only if the commit succeeds (commit hash is not `None`). If the commit fails, the feature directory is preserved so the user can investigate and retry. GitHub branch/PR failures do not roll back the local commit.

## Changes requested

If the architect sets `"action": "changes_requested"`, the workflow writes `completion/changes.md` with feedback and transitions back to `planning` for replanning.
