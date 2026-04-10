# Workflow Phases

> Related source files: `agentmux/shared/phase_catalog.py`, `agentmux/workflow/phase_registry.py`, `agentmux/workflow/phases.py`

This is the canonical reference for AgentMux's workflow phases. Each phase has its own detail page; this index describes the sequence, state machine, and directory layout.

## Phase sequence

| # | Phase | Directory | Optional | Detail |
|---|-------|-----------|----------|--------|
| 1 | `product_management` | `01_product_management/` | yes (`--product-manager` flag) | [01_product-management.md](01_product-management.md) |
| 2a | `architecting` | `02_planning/` | no | [02_planning.md](02_planning.md) |
| 2b | `planning` | `02_planning/` | no | [02_planning.md](02_planning.md) |
| 3 | *(research)* | `03_research/` | on-demand | [02_planning.md § Research](02_planning.md#research-03_research) |
| 4 | `designing` | `04_design/` | yes (`needs_design: true` in plan.yaml) | [04_design.md](04_design.md) |
| 5a | `implementing` | `05_implementation/` | no | [05_implementation.md](05_implementation.md) |
| 6 | `reviewing` | `06_review/` | no | [06_review.md](06_review.md) |
| 5b | `fixing` | `05_implementation/` | yes (after review fail) | [05_implementation.md § Fixing](05_implementation.md#fixing) |
| 8 | `completing` | `08_completion/` | no | [08_completion.md](08_completion.md) |

`architecting` and `planning` share the `02_planning/` directory. `implementing` and `fixing` share `05_implementation/`. Research is a cross-cutting concern triggered during architecting.

## State machine

```
[product_management?] → architecting → planning → [designing?] → implementing → reviewing
                                                                                    │
                                        ┌── review_pass ─────────────────────────→ completing
                                        │
                                        ├── review_fail (loop cap not reached) ──→ fixing → reviewing
                                        │
                                        └── review_fail (loop cap reached) ──────→ completing
                                                                                        │
                                              ┌─ approval_received ──────────────────→ done
                                              └─ changes_requested ──────────────────→ planning
```

`failed` is a terminal virtual phase (no directory) reached via orchestrator interruption.

## Root session files

All files below live directly in `.agentmux/.sessions/<feature-name>/` (not in a phase subdirectory):

| File | Writer | Purpose |
|------|--------|---------|
| `state.json` | orchestrator | Current phase and workflow metadata |
| `requirements.md` | orchestrator | Initial feature request passed to architect |
| `context.md` | orchestrator | Auto-generated session/rules context injected into prompts |
| `runtime_state.json` | orchestrator | Runtime tracking |
| `orchestrator.log` | orchestrator | Orchestrator debug log |
| `created_files.log` | orchestrator | Append-only first-seen file creation log (`YYYY-MM-DD HH:MM:SS  path`) |
| `tool_events.jsonl` | MCP server | Append-only MCP tool-call event log (one JSON object per line) |
| `tool_event_state.json` | orchestrator | Replay cursor for `tool_events.jsonl` (byte offset of last applied event) |

## Authoritative source

`src/agentmux/shared/phase_catalog.py` defines the ordered `PHASE_CATALOG` tuple that drives the monitor, progress bar, and directory mappings. When adding a new phase, update `phase_catalog.py` first, then add a `PhaseDescriptor` in `workflow/phase_registry.py`, and create a matching detail page here.
