## Submitting Your Review

Write `07_review/review.yaml` with the fields below, then call `mcp__agentmux__submit_review()` to validate your file and signal completion.

On pass:
```yaml
verdict: pass
summary: |
  All checks passed. Implementation matches the plan.
commit_message: "feat: implement feature X"  # optional
```

On fail:
```yaml
verdict: fail
summary: |
  Found issues that need fixing.
findings:
  - location: src/file.py:42
    issue: Missing input validation
    severity: high
    recommendation: Add email format check before database lookup.
```

After writing the file, call `mcp__agentmux__submit_review()` (no arguments needed).
