You are the coder agent for this pipeline run, fixing review findings.

<file path="requirements.md">
[[include:requirements.md]]
</file>

<file path="04_planning/plan.md">
[[include:04_planning/plan.md]]
</file>

<file path="07_review/fix_request.md">
[[include:07_review/fix_request.md]]
</file>

Your job:
1. Read the review findings in `07_review/fix_request.md` carefully.
2. Fix each finding in the project directory [[placeholder:project_dir]].
3. Do NOT re-implement from scratch — only address the listed findings.
4. FINAL STEP ONLY — once all fixes are applied, call `mcp__agentmux__submit_done(subplan_index=1)` to signal completion.

[[placeholder:project_instructions]]

Constraints:
- Only fix what the review asks for.
