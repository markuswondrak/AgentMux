# Completing Phase

> Related source files: `agentmux/workflow/phases.py`, `agentmux/integrations/completion.py`, `agentmux/workflow/prompts.py`, `agentmux/sessions/state_store.py`

When the review passes, the workflow terminates all `coder` panes (primary and parallel workers) and transitions directly into `completing`.
Documentation updates are expected to be delivered during implementation and verified in review through the planned task scope (`02_planning/tasks.md`), not via a separate runtime phase.

## Flow

1. **Reviewer runs final confirmation** — The reviewer owns the final confirmation step in `08_completion/confirmation_prompt.md`.

2. **Confirmation prompt displays changed files** — The prompt shows all files detected by `git status --porcelain` from the project directory.

3. **Reviewer-stage preference capture** — During confirmation, the reviewer may write approved reusable preferences to `08_completion/approved_preferences.json`. This proposal is session-scoped; it is not a direct write to project prompt extensions.

4. **`08_completion/approval.json` schema**:
   ```json
   {
     "action": "approve",
     "commit_message": "...",
     "exclude_files": []
   }
   ```

5. **Apply reviewer-approved preferences before commit file selection** — On `approval_received`, `CompletingPhase.handle_event()` first applies `08_completion/approved_preferences.json` (if present). This can append bullets to `.agentmux/prompts/agents/<role>.md`.

6. **Auto-detection and filtering** — The phase reads git status after applying preferences, removes any files listed in `exclude_files`, and passes the remaining file list to `CompletionService.finalize_approval(...)`.

7. **Branch + PR creation (best effort)** — If startup state indicates GitHub is available (`gh_available: true`), `CompletionService` creates a branch (`<github.branch_prefix><feature-slug>`), pushes it, and runs `gh pr create` against `github.base_branch`. PRs default to draft (`github.draft: true`). The PR body is assembled from `requirements.md`, `02_planning/plan.md`, and `06_review/review.md`, and includes `Closes #<N>` when the run started with `--issue`.

8. **Cleanup only on success** — The feature directory is deleted only if the commit succeeds. If the commit fails, the feature directory is preserved so the user can investigate and retry. GitHub branch/PR failures do not roll back the local commit.

Because reviewer-approved preferences are applied before changed-file collection, resulting edits to `.agentmux/prompts/agents/<role>.md` are included in the final changed-file set unless excluded.

## Changes requested

If the reviewer requests changes, the workflow writes `08_completion/changes.md` with feedback and transitions back to `planning` for replanning.
The `changes_requested` path does not apply reviewer preference proposals.
