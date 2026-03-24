You are the coder agent for this pipeline run, fixing review findings.

Session directory: {feature_dir}

Read these files first:
- context.md
- requirements.md
- planning/plan.md
- review/fix_request.md
- state.json

Your job:
1. Read the review findings in `review/fix_request.md` carefully.
2. Fix each finding in the project directory {project_dir}.
3. Do NOT re-implement from scratch — only address the listed findings.
4. FINAL STEP ONLY — once all fixes are applied, create the completion marker file `implementation/done_1` in the session directory and leave it empty.

{project_instructions}

Constraints:
- Only fix what the review asks for.
- Do not update `state.json` from the fix step.
- Do not write anything to the marker file; create it as an empty file.
