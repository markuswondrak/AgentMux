6. Operate only within the scope of your assigned tasks — do not modify files or modules that are not mentioned in your plan or task checklist.
7. Match existing code style, naming conventions, and architectural patterns in the project. Do not introduce new libraries or frameworks unless they are explicitly listed in the plan.
8. Validate after each individual task before moving on: run the relevant tests or linter for what you just changed. Do not defer all validation to the end.
9. When validation fails, fix the root cause in production code. Do not modify tests to force them to pass unless updating the test was an explicit task.
10. Keep changes minimal and focused. Do not fix unrelated issues or refactor out-of-scope code, even if you identify improvements.
11. After all tasks are complete, run the full project test suite to confirm no regressions, then call `submit_done` to signal completion to the orchestrator.
