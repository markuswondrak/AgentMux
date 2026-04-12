# Artifact: Completion Artifacts

> Related source files: `src/agentmux/workflow/handlers/completing.py`, `src/agentmux/terminal_ui/completion_ui.py`, `src/agentmux/integrations/completion.py`

Three artifacts are produced during the completion phase, depending on the user's decision.

---

## `approval.json`

Written by the completion UI when the user approves the implementation.

**Location:** `08_completion/approval.json`

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | string | yes | Always `"approve"`. Used by the orchestrator to distinguish from other completion actions. |
| `exclude_files` | string[] | yes | List of relative file paths to exclude from the commit. Empty array (`[]`) means commit all changed files. |
| `commit_message` | string | no | Optional commit message. When present and non-empty, used verbatim (trimmed) as the final git commit message. When absent or blank, the completing phase drafts a deterministic fallback from `plan.yaml` and session artifacts. |

### Example

```json
{
  "action": "approve",
  "exclude_files": ["debug.log", "scratch.py"],
  "commit_message": "feat(auth): add JWT token service and middleware"
}
```

### Orchestrator behavior

When `approval.json` appears with `action: "approve"`:
1. Files listed in `exclude_files` are removed from the staged set.
2. `commit_message` is used verbatim if present; otherwise, a fallback is drafted.
3. Git stages the remaining changed files, commits, and optionally creates a branch + PR.
4. The feature directory is deleted only on a successful commit.

---

## `changes.md`

Written by the completion UI when the user requests changes instead of approving.

**Location:** `08_completion/changes.md`

### Format

Free-form Markdown. Contains the user's description of what should be changed.

### Orchestrator behavior

When `changes.md` appears, the `changes_requested` event is emitted and the workflow transitions back to `architecting`. The architect receives a re-planning prompt that includes the content of `changes.md`.

### Example

```markdown
The JWT tokens expire too quickly (5 minutes). Please increase the default
expiry to 24 hours and make it configurable via an environment variable.
Also add refresh token support.
```

---

## `.last_completion.json`

Written by the completing phase after a successful commit, at the project-level path (not inside the feature directory).

**Location:** `<project_dir>/.agentmux/.last_completion.json`

This artifact persists after the feature directory is cleaned up. The pipeline reads it after tmux exits to render the final goodbye screen in the original terminal.

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `feature_name` | string | yes | Human-readable feature slug (without timestamp prefix). |
| `commit_hash` | string | yes | Short git commit hash (from `git rev-parse --short HEAD`). |
| `pr_url` | string \| null | yes | URL of the created GitHub PR, or `null` when no PR was created (e.g. `gh` not available, or creation failed). |
| `branch_name` | string | yes | Name of the feature branch that was pushed (e.g. `"feature/my-feature"`). |

### Example

```json
{
  "feature_name": "jwt-auth",
  "commit_hash": "a1b2c3d",
  "pr_url": "https://github.com/org/repo/pull/42",
  "branch_name": "feature/jwt-auth"
}
```

### Notes

- The artifact is only written when the commit succeeds (i.e. a commit hash exists).
- `pr_url` is `null` when GitHub is not configured, `gh` is unavailable, or PR creation fails.
- GitHub branch/PR failures do not prevent writing this artifact or cleaning up the feature directory.
