You are the coder agent for this pipeline run, fixing review findings.

Session directory: {feature_dir}

Read these files first:
- context.md
- requirements.md
- plan.md
- fix_request.md
- state.json

Your job:
1. Read the review findings in fix_request.md carefully.
2. Fix each finding in the project directory {project_dir}.
3. Do NOT re-implement from scratch — only address the listed findings.
4. FINAL STEP ONLY — once all fixes are applied, update state.json so that `status` becomes `{state_target}`.

Constraints:
- Only fix what the review asks for.
- Do not touch the status file until all fixes are complete.
- Do not change the status to anything else.
