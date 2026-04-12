# Session Resumption

> Related source file: `src/agentmux/sessions/state_store.py`

When a pipeline is interrupted (e.g., connection loss, tmux session killed, or a user manually closes an agent pane with `Ctrl-C`), it can be restarted from where it left off using `resume`.

## CLI usage

```bash
agentmux resume                         # Interactive selection from existing sessions
agentmux resume <feature-dir-or-name>  # Resume specific session by name or path
```

## Flow

1. `list_resumable_sessions(project_dir)` scans `.agentmux/.sessions/` for all feature directories with `state.json` and returns them sorted by recency
2. `select_session(sessions)` presents an interactive menu (or auto-selects if only one exists)
3. For `resume <feature-dir-or-name>`, non-absolute names are resolved against `.agentmux/.sessions/<name>` first, then `<project>/<name>` as a fallback
4. `infer_resume_phase(feature_dir, state)` examines workflow artifacts (`01_product_management/done`, `04_planning/plan.md`, `04_planning/execution_plan.yaml`, `06_implementation/done_*`, `07_review/review.md` / `07_review/review.yaml`, etc.) together with persisted workflow state to determine the correct phase to resume into
5. If `"product_manager": true` in state and `01_product_management/done` is missing, resume returns `product_management`; once `done` exists, resume falls through to normal `04_planning` / `06_implementation` inference
6. `execution_plan.yaml` is used as planner-authored intent metadata during inference:
   - `needs_design: true` resumes into `designing` when `05_design/design.md` is still missing
   - `needs_docs`/`doc_files` remain planning metadata and do not create a dedicated resume phase
   - a passed review resumes directly into `completing`
7. Session identity is persisted in `state.json` as `session_name`; resume reads that value and falls back to `defaults.session_name` only for legacy states that do not yet have the field
8. Resume hard-blocks if that recovered tmux session is still active (`tmux session <name> is still active. Detach or kill it before resuming.`)
9. On resume, the phase is updated in `state.json`, `last_event` is set to `"resumed"`, and in-flight research task statuses remain in `state.json` so they can be restarted from persisted workflow state
10. The launcher derives the initial tmux pane from the resumed phase via `PHASE_REGISTRY` metadata instead of reusing the original session entrypoint (`product-manager` vs `architect`)
11. Orchestrator/monitor entrypoints infer the project directory from session paths under `.agentmux/.sessions/<id>`
12. The background orchestrator explicitly re-enters the current phase before starting file/interruption sources, so resume prompt dispatch is deterministic and no longer depends on the first seeded file event
13. `runtime_state.json` is treated as advisory recovery data for panes/PIDs, while `tool_event_state.json` persists the last applied `tool_events.jsonl` cursor so resume replays only unapplied tool signals
14. `implementing` and `fixing` explicitly clear the primary `coder` pane before dispatch so resume never reuses an old shell after the prior coder CLI has exited
15. `implementation_single_coder` is persisted on entering the implementing phase; on resume, the handler restores this setting so the same dispatch mode (whole-plan vs per-group) is used regardless of current agent configuration
16. After the resumed phase is entered and unapplied tool events are replayed, any still-dispatched research subtasks are restarted from their persisted `03_research/<type>-<topic>/prompt.md` directories
17. If the prior run failed because a registered tmux agent pane disappeared, the interruption metadata in `state.json` is cleared on resume and a fresh pane is created only when the resumed phase next needs that role
