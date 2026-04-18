# Phase: Validating

> Related source files: `src/agentmux/shared/phase_catalog.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/handlers/validating.py`, `src/agentmux/workflow/validation.py`, `src/agentmux/configuration/__init__.py`, `src/agentmux/shared/models.py`, `src/agentmux/runtime/__init__.py` (`run_validation_pane`), `src/agentmux/workflow/event_catalog.py`, `src/agentmux/workflow/prompts.py`, `src/agentmux/prompts/commands/review.md`, `src/agentmux/prompts/commands/review_followup.md`

> Directory: `06_implementation/` (same working tree as `implementing`) | Optional: yes (shown in the monitor progress bar only while active)

## Conditions

Entered from `implementing` or `fixing` on `implementation_completed` when scheduled work finishes all `done_*` markers. The subsequent phase from the implementation handler is `validating` (see `ImplementingHandler` / `FixingHandler`); `ValidatingHandler.enter()` then either fast-paths to `reviewing` or runs automated checks.

## Configuration

Project (`/.agentmux/config.yaml`) and layered configs may define:

```yaml
validation:
  commands: []
```

- `validation.commands` — ordered list of shell strings passed to `python -m agentmux.workflow.validation`, which records structured JSON into `06_implementation/validation_result.json`. The default is an empty list; when empty, `ValidatingHandler` **immediately** transitions to `reviewing` without spawning a pane.

See [configuration: validation](../configuration.md#validation-settings).

## Runtime: validation pane

When `validation.commands` is non-empty, `ValidatingHandler.enter()` spawns a temporary pane via `TmuxAgentRuntime.run_validation_pane(cmd, "Validating")`. The command runs the validation runner against the project directory; the pane is shown while work runs but is **not** registered as a primary or parallel agent pane. When `validation_result.json` appears and parses, the handler applies the payload (`handle_event` on the `validation_result` file event).

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `06_implementation/validation_result.json` | `agentmux.workflow.validation` CLI (via validation pane) | `ValidatingHandler` | JSON (`passed`, command output fields) |
| `07_review/validation_status.md` | `ValidatingHandler` on pass | reviewer command prompt build (`[[include-optional:…]]` in `review.md` / `review_followup.md`) | Markdown |
| `07_review/validation_failure.log` | `ValidatingHandler` on fail | coder (during fixing) | Text |
| `07_review/fix_request.md` | `ValidatingHandler` on fail | coder (during fixing) | Markdown |

Reviewer command templates include `[[include-optional:07_review/validation_status.md]]`. When the file is **missing**, expansion is silent (empty insertion).

## Workflow events

- `EVENT_VALIDATION_PASSED` (`validation_passed`) — automated checks succeeded; handler transitions to `reviewing`.
- `EVENT_VALIDATION_FAILED` (`validation_failed`) — a command failed; handler increments `review_iteration`, writes fix-request artifacts, transitions to `fixing`.

## Transitions

| From | Condition | To |
|------|-----------|-----|
| `implementing` / `fixing` | `implementation_completed` (all markers done) | `validating` |
| `validating` | `validation.commands` empty | `reviewing` (immediate) |
| `validating` | `validation_result.json` indicates `passed: true` | `reviewing` |
| `validating` | `validation_result.json` indicates `passed: false` | `fixing` |

## Notes

- Optional phases are hidden from the monitor progress bar until they become the active phase (`OPTIONAL_PHASES` in `phase_catalog.py`).
- Resume with `last_event == resumed` and an existing `validation_result.json` replays `_apply_validation_payload` without re-running the pane (`ValidatingHandler.enter()`).
- Orchestrator resume uses the persisted `phase` field in `state.json`. See [Session resumption](../session-resumption.md).
