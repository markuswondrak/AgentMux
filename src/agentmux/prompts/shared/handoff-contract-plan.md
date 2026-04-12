## Submitting Your Plan

Write a single `04_planning/plan.yaml` containing all sub-plans and execution metadata, then call `mcp__agentmux__submit_plan()` once.

```yaml
version: 2
plan_overview: |
  # Implementation Plan

  Overview of all planned work.
review_strategy:
  severity: medium   # low | medium | high
  focus:
    - security       # optional focus areas
needs_design: false
needs_docs: true
doc_files:
  - docs/api.md
groups:
  - group_id: core-setup
    mode: serial     # serial | parallel
    plans:
      - index: 1
        name: Core setup
subplans:
  - index: 1
    title: Short descriptive title
    scope: What this sub-plan covers
    owned_files:
      - src/auth.py
      - tests/test_auth.py
    dependencies: None
    implementation_approach: |
      Step-by-step approach.
    acceptance_criteria: |
      Testable criteria for completion.
    tasks:
      - First task
      - Second task
    isolation_rationale: |  # optional
      Why this sub-plan is safe for parallel execution.
```

After writing the file, call `mcp__agentmux__submit_plan()` (no arguments needed).

Each sub-plan in `subplans` must be referenced exactly once in `groups[].plans[]` via its `index`. Indices must start at 1 and be contiguous (1, 2, 3, …).
