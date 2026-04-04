You have just completed a successful code review (verdict: pass). Now write a concise
implementation summary for the user.

Session directory: [[placeholder:feature_dir]]

<file path="requirements.md">
[[include:requirements.md]]
</file>

<file path="02_planning/plan.md">
[[include:02_planning/plan.md]]
</file>

<file path="06_review/review.md">
[[include:06_review/review.md]]
</file>

Your job:
1. Write `08_completion/summary.md` with a plain-language summary of what was implemented.
   Use this structure:
   ```
   ## What was implemented

   <2-5 bullet points describing the key features or changes delivered>

   ## Key decisions

   <1-3 bullets on notable technical choices, if any>

   ## Deviations from plan

   <Any gaps or intentional scope changes; write "None" if everything was delivered as planned>
   ```
2. Optionally write `[[placeholder:reviewer_preference_proposal_file]]` if you have approved
   reusable preferences to record for future sessions:
   `{{"source_role":"reviewer","approved":[{{"target_role":"coder","bullet":"- ..."}}]}}`
   Skip this file entirely if you have no approved preferences.

FINAL STEP ONLY — once `08_completion/summary.md` is fully written, stop.
Do not update `state.json` or any other workflow file.

[[placeholder:project_instructions]]

Constraints:
- Keep the summary factual and brief — this is shown to the user on the confirmation screen.
- Do not re-open code files or run tests; rely on the review and plan you already have.
- Do not interact with the user.
