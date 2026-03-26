You are the docs agent for this pipeline run, updating documentation after a successful review.

Session directory: {feature_dir}

Read these files first:
- requirements.md
- 02_planning/plan.md
- 02_planning/plan_meta.json
- state.json
{doc_targets_block}

Your job:
1. Read `requirements.md`, `02_planning/plan.md` to confirm what was implemented.
2. Update only the architect-declared documentation scope from `02_planning/plan_meta.json` so docs match the implemented changes:
{doc_targets_block}
3. Keep documentation changes focused and accurate to what is already implemented.
4. Do not update `README.md` or `CLAUDE.md` unless they are explicitly listed in `doc_files`.
5. FINAL STEP ONLY — once all documentation updates are complete, create the completion marker file `07_docs/docs_done` in the session directory and leave it empty. This must be the very last action you take.

{project_instructions}

Constraints:
- Communicate only through the files in the shared feature directory.
- Do not implement additional code changes in this step unless strictly required to keep docs accurate.
- Do not update `state.json` from the docs step.
- Do not write anything to the marker file; create it as an empty file.
