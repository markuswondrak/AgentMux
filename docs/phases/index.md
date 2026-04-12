# Workflow Phases

> Related source file: `src/agentmux/shared/phase_catalog.py`

This is the canonical reference for AgentMux's workflow phases. Each phase has its own detail page; this index describes the sequence, state machine, and directory layout.

## Phase sequence

| # | Phase | Directory | Optional | Detail |
|---|-------|-----------|----------|--------|
| 1 | `product_management` | `01_product_management/` | yes (`--product-manager` flag) | [01_product-management.md](01_product-management.md) |
| 2 | `architecting` | `02_architecting/` | no | [02_architecting.md](02_architecting.md) |
| 3 | *(research)* | `03_research/` | on-demand | [02_architecting.md § Research](02_architecting.md#research-03_research) |
| 4 | `planning` | `04_planning/` | no | [04_planning.md](04_planning.md) |
| 5 | `designing` | `05_design/` | yes (`needs_design: true` in plan.yaml) | [05_design.md](05_design.md) |
| 6 | `implementing` | `06_implementation/` | no | [06_implementation.md](06_implementation.md) |
| 7 | `reviewing` | `07_review/` | no | [07_review.md](07_review.md) |
| 6b | `fixing` | `06_implementation/` | yes (after review fail) | [06_implementation.md § Fixing](06_implementation.md#fixing) |
| 8 | `completing` | `08_completion/` | no | [08_completion.md](08_completion.md) |

`implementing` and `fixing` share `06_implementation/`. Research is a cross-cutting concern triggered during architecting (and by planner/product-manager if needed).

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
                                              └─ changes_requested ──────────────────→ architecting
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
