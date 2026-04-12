## Preference memory at phase-end approval

During the final approval conversation for this phase:

1. Derive candidates only from explicit human feedback in this session (requested changes, user-endorsed edits, or user corrections).
2. Keep only standing preferences reusable across future features (style, process, architecture, tooling).
3. Exclude one-time feedback specific to this feature (single bug fixes, typos, or scope-only corrections).
4. Use the `[[placeholder:user_ask_tool]]` tool to present each candidate with a target-role tag and ask the user to approve, edit, or dismiss each candidate.
5. Do not persist anything without explicit user approval.
6. After the user approves one or more candidates, pass them via the `preferences` parameter when calling your submit tool:
   ```
   preferences=[
     {"target_role": "coder", "bullet": "- Keep tests focused on a single behavior"},
     {"target_role": "coder", "bullet": "- Prefer guard clauses over nested conditionals"}
   ]
   ```
7. If no candidates are approved, omit the `preferences` parameter entirely.
