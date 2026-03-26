# Tmux Session Layout and Pane Management

> Related source files: `agentmux/tmux.py`, `agentmux/runtime.py`, `agentmux/interruption_sources.py`, `agentmux/pipeline.py`

## Content zone

The tmux layout is split into two zones:

- **Monitor zone** on the left, fixed to 15 columns
- **Content zone** on the right, managed exclusively by `ContentZone`

`ContentZone` owns the right-hand pane state. Its `_visible` list is the single source of truth for which agent panes are currently mounted in the main window. The placeholder pane is internal and never part of `_visible`.

## Invariant

- If `_visible` is empty, the placeholder pane occupies the content zone in the main window
- If `_visible` is non-empty, the placeholder pane lives in `_hidden`
- Every `show()`, `show_parallel()`, `hide()`, `hide_all()`, and `remove()` mutation re-establishes that invariant immediately

This avoids reconstructing visibility from ad-hoc tmux queries and keeps placeholder handling confined to one abstraction.

## Pane lifecycle

- **Exclusive display**: `ContentZone.show(pane_id)` swaps a single agent into the content zone and parks any other visible agents
- **Parallel display**: `ContentZone.show_parallel(pane_ids)` shows the first pane exclusively, then stacks the rest vertically with `join-pane -v`
- **Parking**: hidden agents are moved to the `_hidden` window with `break-pane -d`
- **Removal**: `ContentZone.remove(pane_id)` hides a visible pane if needed, then kills it

The monitor/content split is only created once during session setup. Later mutations use swaps, vertical joins, and breaks so the horizontal divider stays stable.

## Pane creation

`create_agent_pane()` always seeds new panes from `_hidden` if possible. If the placeholder is currently the only pane in the content zone, tmux may briefly split against it and immediately break the new pane back into `_hidden`; the steady-state result is still that background panes are parked and not left in the main layout.

`tmux_new_session()` returns both the initial pane registry and a `ContentZone` instance initialized with the primary role visible and the placeholder parked.

## Runtime snapshot

`runtime_state.json` is version 2 and persists:

- `primary`: primary pane IDs per role
- `parallel`: worker/task pane IDs
- `visible`: ordered pane IDs currently shown in the content zone

On resume, `TmuxAgentRuntime.attach()` rehydrates pane IDs, reconstructs `ContentZone` from `visible`, and reapplies the desired layout.

## Missing panes

`TmuxAgentRuntime` also exposes a read-only view of the registered primary and parallel panes. The background `InterruptionEventSource` polls that registry and publishes an interruption event when any registered agent pane disappears, even if it was parked in `_hidden`.

That is treated as a user-visible run cancellation rather than a silent pane recreation. The orchestrator persists the interruption to `state.json`, shows the cause in the monitor, and requires `--resume` to continue.

## Prompt dispatch

`send_prompt()` no longer creates or reveals panes. It only sends a concise file reference message such as:

```text
Read and follow the instructions in /path/to/prompt.md
```

Visibility is decided in `TmuxAgentRuntime` before prompt dispatch. Primary panes are auto-created only when no pane is registered for that role; if a registered pane vanished unexpectedly, the run is canceled instead.

## Trust prompt handling

Trust or confirmation prompts from CLI tools are still answered automatically via `accept_trust_prompt()`, using the provider-specific `trust_snippet` on `AgentConfig`.
