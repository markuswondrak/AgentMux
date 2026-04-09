## Submitting Your Review

Write `06_review/review.yaml` with the fields below, then call `submit_review()` to validate your file and signal completion. The orchestrator observes the file and materializes `review.md` automatically.

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

After writing the file, call `submit_review()` (no arguments needed). The tool validates your YAML and signals the orchestrator to advance the workflow. If validation fails, it returns an error so you can correct the file.
