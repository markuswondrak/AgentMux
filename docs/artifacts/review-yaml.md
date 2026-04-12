# Artifact: review.yaml

> Related source files: `src/agentmux/workflow/handoff_contracts.py`, `src/agentmux/workflow/handlers/reviewing.py`, `src/agentmux/integrations/mcp_server.py`

`review.yaml` is the structured review verdict produced by a reviewer agent and submitted via the `submit_review` MCP tool. The orchestrator materializes `review.md` from it if the Markdown companion is missing.

**Location:** `07_review/review.yaml`

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `verdict` | string | yes | Review outcome: `"pass"` or `"fail"`. |
| `summary` | string | yes | Human-readable summary of what was reviewed and the overall finding. |
| `findings` | list[dict] | on `fail` | List of individual issues found. Required (and non-empty) when `verdict` is `"fail"`. Not required on `"pass"`. See [findings fields](#findings-fields). |
| `commit_message` | string | no | Suggested commit message. On `"pass"`, the completing phase uses this verbatim (trimmed) as the final commit message. When omitted or blank, completion drafts a deterministic fallback from session artifacts. |

## `findings` fields

Each entry in `findings` describes a single issue:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `location` | string | no | File path and optional line number (e.g. `"src/auth.py:42"`). Helps the coder navigate to the problem. |
| `issue` | string | yes | Clear description of the problem found. |
| `severity` | string | no | Severity level: `"critical"`, `"high"`, `"medium"`, `"low"`, or `"info"`. |
| `recommendation` | string | yes | Concrete suggestion for how to fix the issue. |

## Validation rules

- `verdict` must be `"pass"` or `"fail"`.
- When `verdict` is `"fail"`, `findings` must be a non-empty list.
- Each finding must have a non-empty `issue` and `recommendation`.
- On `"pass"`, `findings` is ignored (may be absent or empty).

## Pass example

```yaml
verdict: pass
summary: |
  Implementation matches the plan. JWT token generation and validation
  are correct, middleware integrates cleanly, and all tests pass.
commit_message: "feat(auth): add JWT token service and middleware"
```

## Fail example

```yaml
verdict: fail
summary: |
  Token expiry is not handled — expired tokens pass validation silently.
  Two findings require fixing before the review can pass.
findings:
  - location: src/auth/tokens.py:34
    issue: validate_token does not check the 'exp' claim — expired tokens are accepted.
    severity: critical
    recommendation: |
      Add `options={"verify_exp": True}` to the jwt.decode() call and
      catch jwt.ExpiredSignatureError, returning None on expiry.
  - location: tests/test_tokens.py
    issue: No test for expired token rejection.
    severity: high
    recommendation: |
      Add a test that generates a token with exp=now()-1s and asserts
      validate_token returns None.
```

## Companion artifact: review.md

`review.md` is a human-readable Markdown rendering of `review.yaml`. It is used in PR descriptions, the monitor, and completion prompts. If `review.md` is missing when it is needed, AgentMux generates it automatically from `review.yaml`.
