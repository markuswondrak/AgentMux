# Completing Phase

> Related source files: `agentmux/workflow/phases.py`, `agentmux/workflow/handlers/reviewing.py`, `agentmux/workflow/handlers/completing.py`, `agentmux/integrations/completion.py`, `agentmux/workflow/prompts.py`, `agentmux/sessions/state_store.py`, `agentmux/terminal_ui/completion_ui.py`

When the review passes, the workflow kills all `coder` panes and sends the reviewer a follow-up prompt to write an implementation summary. Once the summary is written, the reviewer is killed and the workflow transitions into `completing`.

## Flow

1. **VERDICT:PASS → reviewer writes summary** — The reviewing handler sends `08_completion/summary_prompt.md` to the reviewer (stays in `reviewing` phase with `awaiting_summary: true` in state). The summary prompt asks the reviewer to write `08_completion/summary.md` describing what was implemented.

2. **Summary written → reviewer killed → completing entered** — When `08_completion/summary.md` appears, the reviewing handler kills the reviewer pane and transitions to `completing`.

3. **Completion entry mode is selected** — The phase checks `workflow_settings.completion.skip_final_approval`.
   - `false` (default): a native terminal UI is launched in the content zone tmux pane (`python -m agentmux.terminal_ui.completion_ui --feature-dir <path>`).
   - `true`: completion auto-prepares approval inside `08_completion/approval.json` with `{"action": "approve", "exclude_files": []}`.
   In both modes, the workflow still enters `completing`, and `completing` remains the owner of commit, cleanup, and PR finalization.

4. **Native confirmation UI** — The TUI displays the agentmux logo, the reviewer summary rendered as Markdown (headings, bold, lists, code blocks), the count of changed files, and a `[Y] / [N]` confirmation panel. The `[N]` option includes a visual affordance (`❯ describe what to change`) indicating that a text prompt follows. If the user presses `Y`, it writes `08_completion/approval.json`. If the user presses `N`, it prompts for feedback text and writes `08_completion/changes.md`. Typing `/cancel` or pressing `Ctrl+C` during the feedback prompt cancels and returns to the `[Y] / [N]` screen.

5. **Reviewer-stage preference capture** — The reviewer may pass approved preferences via the `preferences` parameter on `submit_review`. These are written directly to `.agentmux/prompts/agents/<role>.md` under `## Approved Preferences` — no intermediate JSON file is used.

6. **`08_completion/approval.json` schema**:
   ```json
   {
     "action": "approve",
     "exclude_files": [],
     "commit_message": "optional reviewer summary"
   }
   ```
   - `commit_message` is optional.
   - When present, completion uses it verbatim as the final commit message (trimmed).
   - When omitted or blank, completion drafts a deterministic fallback from session artifacts.

7. **Auto-detection and filtering** — The phase reads git status, removes any files listed in `exclude_files`, resolves the commit message via `CompletionService.resolve_commit_message(...)`, and passes the resulting message into `CompletionService.finalize_approval(...)`.
   - In manual confirmation mode, reviewer-provided `commit_message` in `approval.json` takes precedence.
   - In auto-approval mode, the generated approval artifact usually omits `commit_message`, so completion uses the same deterministic draft fallback path.

8. **Branch + PR creation (best effort)** — If startup state indicates GitHub is available (`gh_available: true`), `CompletionService` creates a branch (`<github.branch_prefix><feature-slug>`), pushes it, and runs `gh pr create` against `github.base_branch`. PRs default to draft (`github.draft: true`). The PR body is assembled from `requirements.md`, `02_planning/plan.yaml` (`plan_overview` field, falling back to `plan.md`), and `06_review/review.md`, and includes `Closes #<N>` when the run started with `--issue`.

9. **Completion summary artifact is written before cleanup** — On successful completion (when a commit hash exists), completion writes `<project_dir>/.agentmux/.last_completion.json` before removing the feature directory. The pipeline reads this artifact after tmux exits to render the final goodbye screen in the original terminal.
    - JSON schema:
      ```json
      {
        "feature_name": "my-feature",
        "commit_hash": "abc1234",
        "pr_url": "https://github.com/org/repo/pull/42",
        "branch_name": "feature/my-feature"
      }
      ```
    - `pr_url` may be `null` when no PR is created.
    - The artifact is skipped when completion does not produce a commit hash.

10. **Cleanup only on success** — The feature directory is deleted only if the commit succeeds. If the commit fails, the feature directory is preserved so the user can investigate and retry. GitHub branch/PR failures do not roll back the local commit.

## Changes requested

If the user enters `N` in the confirmation UI and provides feedback, the TUI writes `08_completion/changes.md` and the workflow transitions back to `planning` for replanning.
