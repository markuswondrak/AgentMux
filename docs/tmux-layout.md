# Tmux Session Layout and Pane Management

> Related source files: `agentmux/tmux.py`, `agentmux/runtime.py`

## Zone approach

The tmux layout uses a "zone" approach: the **monitor zone** (left, fixed 15 cols) and the **agent zone** (right, remaining space). The control pane width is set once at session creation via `resize-pane -x 15` and never touched programmatically again.

Pane border titles are enabled at session creation (`pane-border-status top`). The `pane-border-format` uses a conditional: agent panes (non-empty title) show `bold role · dim feature-slug`; the monitor pane has an empty title and shows nothing in the border. The monitor pane ID is stored in the tmux session environment as `CONTROL_PANE` (analogous to `PLACEHOLDER_PANE`) and looked up via `_find_control_pane()` rather than by title scan.

## Pane lifecycle

- **Exclusive mode**: Agents are swapped into the right zone via `swap-pane` — only one agent visible at a time
- **Parallel mode**: Agents are stacked with `join-pane -v` — multiple agents visible simultaneously
- **Parking**: Idle agents are parked in a hidden `_hidden` window via `break-pane -d`

None of these operations affect the horizontal partition, so the monitor width stays rock-solid.

## Key functions

- `send_prompt()` in `agentmux/tmux.py` — sends a concise file reference message to the agent pane (e.g., "Read and follow the instructions in `/path/to/prompt.md`"). The agent reads the file itself.
- `tmux_*` helpers in `agentmux/tmux.py` — create/kill sessions, panes, capture output
- `_fix_control_width()` in `agentmux/tmux.py` — one-shot resize fallback, only used when the right zone was empty

## Trust prompt handling

Trust/confirmation prompts from CLI tools are automatically answered with Enter. The `trust_snippet` field on `AgentConfig` defines what text to detect for each provider.
