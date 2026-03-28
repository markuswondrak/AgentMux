# Session Resumption

> Related source files: `agentmux/pipeline/__init__.py`, `agentmux/pipeline/application.py`, `agentmux/terminal_ui/console.py`, `agentmux/sessions/__init__.py`, `agentmux/sessions/state_store.py`, `agentmux/runtime/__init__.py`

When a pipeline is interrupted (e.g., connection loss, tmux session killed, or a user manually closes an agent pane with `Ctrl-C`), it can be restarted from where it left off using `--resume`.

## CLI usage

```bash
agentmux --resume                         # Interactive selection from existing sessions
agentmux --resume <feature-dir-or-name>  # Resume specific session by name or path
```

## Flow

1. `list_resumable_sessions(project_dir)` scans `.agentmux/.sessions/` for all feature directories with `state.json` and returns them sorted by recency
2. `select_session(sessions)` presents an interactive menu (or auto-selects if only one exists)
3. For `--resume <feature-dir-or-name>`, non-absolute names are resolved against `.agentmux/.sessions/<name>` first, then `<project>/<name>` as a fallback
4. `infer_resume_phase(feature_dir, state)` examines workflow artifacts (`01_product_management/done`, `02_planning/plan.md`, `02_planning/plan_meta.json`, `05_implementation/done_*`, `06_review/review.md`, etc.) to determine the correct phase to resume into
5. If `"product_manager": true` in state and `01_product_management/done` is missing, resume returns `product_management`; once `done` exists, resume falls through to normal `02_planning` / `05_implementation` inference
6. `plan_meta.json` is used as architect-authored intent metadata during inference:
   - `needs_design: true` resumes into `designing` when `04_design/design.md` is still missing
   - `needs_docs`/`doc_files` remain planning metadata and do not create a dedicated resume phase
   - a passed review resumes directly into `completing`
7. On resume, the phase is updated in `state.json`, `last_event` is set to `"resumed"`, and any research tasks with `"dispatched"` status are cleaned up (allowing re-request)
8. Orchestrator/monitor entrypoints infer the project directory from session paths under `.agentmux/.sessions/<id>`
9. The orchestrator picks up the updated state and injects the appropriate phase prompt to resume work
10. `implementing` and `fixing` explicitly clear the primary `coder` pane before dispatch so resume never reuses an old shell after the prior coder CLI has exited
11. If the prior run failed because a registered tmux agent pane disappeared, the interruption metadata in `state.json` is cleared on resume and a fresh pane is created only when the resumed phase next needs that role
