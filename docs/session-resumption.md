# Session Resumption

> Related source files: `pipeline.py` (shim), `agentmux/pipeline.py`, `agentmux/config.py`, `agentmux/state.py`, `agentmux/runtime.py`

When a pipeline is interrupted (e.g., connection loss, tmux session killed), it can be restarted from where it left off using `--resume`.

## CLI usage

```bash
python3 pipeline.py --resume                         # Interactive selection from existing sessions
python3 pipeline.py --resume <feature-dir-or-name>  # Resume specific session by name or path
```

## Flow

1. `list_resumable_sessions(project_dir)` scans `.agentmux/.sessions/` for all feature directories with `state.json` and returns them sorted by recency
2. `select_session(sessions)` presents an interactive menu (or auto-selects if only one exists)
3. For `--resume <feature-dir-or-name>`, non-absolute names are resolved against `.agentmux/.sessions/<name>` first, then `<project>/<name>` as a fallback
4. `infer_resume_phase(feature_dir, state)` examines workflow artifacts (`01_product_management/done`, `02_planning/plan.md`, `05_implementation/done_*`, `06_review/review.md`, etc.) to determine the correct phase to resume into
5. If `"product_manager": true` in state and `01_product_management/done` is missing, resume returns `product_management`; once `done` exists, resume falls through to normal `02_planning` / `05_implementation` inference
6. On resume, the phase is updated in `state.json`, `last_event` is set to `"resumed"`, and any research tasks with `"dispatched"` status are cleaned up (allowing re-request)
7. Orchestrator/monitor entrypoints infer the project directory from session paths under `.agentmux/.sessions/<id>` and also keep compatibility with legacy `.multi-agent/<id>` directories
8. The orchestrator picks up the updated state and injects the appropriate phase prompt to resume work
9. `implementing` and `fixing` explicitly clear the primary `coder` pane before dispatch so resume never reuses an old shell after the prior coder CLI has exited
