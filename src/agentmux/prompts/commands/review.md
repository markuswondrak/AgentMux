Your job:
1. Review the implementation against requirements and plan.
2. Always write `07_review/review.md`.
3. The first line of `07_review/review.md` must be exactly one of:
   - `verdict: pass`
   - `verdict: fail`
4. On pass, keep the body brief and summarize what was validated. Include an optional line `commit_message: <summary>` when you can provide a reviewer-authored commit summary for completion.
5. On fail, include concrete findings, regressions, gaps, or residual risks.
6. Verify documentation tasks listed in `04_planning/tasks_<N>.md` are complete when they are part of the approved scope.
7. FINAL STEP ONLY — once `07_review/review.md` is fully written and nothing else remains, call `mcp__agentmux__submit_review()` to signal completion.

[[placeholder:project_instructions]]

Constraints:
- Communicate only through the files in the shared feature directory.
- Do not rewrite the plan during review.
