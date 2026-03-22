# Session Resumption

> Related source files: `pipeline.py`, `src/state.py`, `src/runtime.py`

When a pipeline is interrupted (e.g., connection loss, tmux session killed), it can be restarted from where it left off using `--resume`.

## CLI usage

```bash
python3 pipeline.py --resume                         # Interactive selection from existing sessions
python3 pipeline.py --resume <feature-dir-or-name>  # Resume specific session by name or path
```

## Flow

1. `list_resumable_sessions(project_dir)` scans `.multi-agent/` for all feature directories with `state.json` and returns them sorted by recency
2. `select_session(sessions)` presents an interactive menu (or auto-selects if only one exists)
3. `infer_resume_phase(feature_dir, state)` examines workflow artifacts (`planning/plan.md`, `implementation/done_*`, `review/review.md`, etc.) to determine the correct phase to resume into
4. On resume, the phase is updated in `state.json`, `last_event` is set to `"resumed"`, and any research tasks with `"dispatched"` status are cleaned up (allowing re-request)
5. The orchestrator picks up the updated state and injects the appropriate phase prompt to resume work
