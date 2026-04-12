Constraints:
- Communicate only through files in the session directory. This means research outputs — do not message other agents or modify the project directory.
- The `submit_research_done` MCP call is the **only** valid completion signal. The orchestrator does NOT detect your output files automatically — it will wait indefinitely until you make this call.
- Do not invent facts.
- Do not ask questions. If the scope is unclear, use your best judgment and document your interpretation.
- Only write files in the session directory. Do not create or modify any files in the project directory.
