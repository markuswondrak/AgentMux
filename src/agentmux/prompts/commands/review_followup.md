Follow-up Review — iteration [[placeholder:review_iteration]]

You are still [[placeholder:review_role]] for this pipeline run.
The coder has addressed the findings from your previous review. Re-check
only whether those findings are resolved. Do not re-read the architecture,
plan, or context files — they have not changed. Do not expand scope.

Your previous findings (role-specific):
<file path="[[placeholder:previous_review_file]]">
[[include:[[placeholder:previous_review_file]]]]
</file>

Aggregated fix request the coder worked from:
<file path="[[placeholder:fix_request_file]]">
[[include:[[placeholder:fix_request_file]]]]
</file>

Task:
1. Verify whether each of your previous findings is now resolved.
2. Do not open issues outside your role's scope.
3. Write `07_review/review_[[placeholder:review_role]].yaml` with `verdict: pass` or `verdict: fail`.
   On `fail`, list only the findings that are still unresolved (or newly introduced by the fix).
4. FINAL STEP ONLY — once the YAML is fully written, call `mcp__agentmux__submit_review()` to signal completion.

[[placeholder:project_instructions]]

Constraints:
- Communicate only through files in the shared feature directory.
- Do not modify project files or re-run unchanged checks against other roles.
