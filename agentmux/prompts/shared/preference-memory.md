## Preference memory at phase-end approval

During the final approval conversation for this phase:

1. Derive candidates only from explicit human feedback in this session (requested changes, user-endorsed edits, or user corrections).
2. Keep only standing preferences reusable across future features (style, process, architecture, tooling).
3. Exclude one-time feedback specific to this feature (single bug fixes, typos, or scope-only corrections).
4. Before proposing candidates, check existing prompt extension files in `{project_dir}/.agentmux/prompts/agents/<role>.md`.
5. Present each candidate with a target-role tag and ask the user to approve, edit, or dismiss each candidate.
6. Do not persist anything without explicit user approval.
