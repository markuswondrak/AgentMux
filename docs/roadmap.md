---
title: Roadmap
description: Where AgentMux is today and where it is going.
---

<!--
HOW TO USE THIS FILE
====================

This markdown file is the single source of truth for the AgentMux roadmap.
Editing it updates two places on the website:

  - /docs/roadmap — renders this document as-is
  - /roadmap      — renders a visual board, data extracted by scripts/sync-docs.mjs

Format — the sync script parses this exact structure:

  ## <Column title>               ← H2 heading becomes a column on /roadmap

  <any prose here is rendered on the docs page but ignored by the parser>

  - **<Item title>** · <status> · <CATEGORY> [· #<issue>]
    <optional description paragraph, indented under the bullet>

Allowed status values: deployed | in_progress | ambitious
Category is an UPPERCASE tag (letters and digits only).
Issue reference is optional — e.g. `· #104`.

To update the roadmap, edit this file and rerun `pnpm sync-docs` in website/.
The parser will fail the build if a bullet is missing a valid status.
-->

# Roadmap

AgentMux is a meta-orchestrator for multi-agent software workflows that leans on the robustness of `tmux`. The north star is to connect local terminal execution with seamless IDE integration and cloud-grade scalability — using the AI subscriptions developers already have, instead of paying per token.

Status values carry a specific meaning:

- **deployed** — lives on `main` today and is exercised by the pipeline.
- **in_progress** — active work in flight, usually on a feature branch.
- **ambitious** — on the direction of travel, not yet in flight.

## Foundation

Everything in this column already works end-to-end.

- **Multi-agent tmux runtime** · deployed · RUNTIME
  Deterministic spawn and teardown of agent panes in a single tmux session, with a monitor pane for live observation and intervention.

- **Event-driven orchestrator** · deployed · ORCHESTRATION
  Shared event bus with file, tool-call and interruption sources. Handlers emit structured workflow events — no busy-waiting, no artifact-sniffing.

- **Phase state machine** · deployed · WORKFLOW
  Product management, architecting, planning, design, implementation, review and completion, with a bounded review loop and a replanning exit. Durable state lives in `state.json`.

- **Multi-provider bridge** · deployed · PROTOCOL
  One handoff contract across `claude`, `codex`, `copilot`, `gemini`, `opencode` and `qwen`. Trust prompts are answered automatically; per-provider stdin modes are handled under the hood.

- **Handoff contracts** · deployed · MCP
  Structured handoff contracts validated at MCP submit time, with dual-file output that downstream phases consume directly. Replaces freeform agent output drift between phases.

- **Public docs and website** · in_progress · DOCS · #104
  Landing page, editorial design system, ported architecture diagram and the full documentation set, deployed to GitHub Pages.

## Ecosystem

The next wave is about lowering the barrier to entry and opening AgentMux to other tools.

- **Workflow presets (scopes)** · ambitious · SCOPES
  Opinionated, pre-configured agent setups in three sizes so users can start a pipeline in one command instead of hand-wiring phases.

- **Declarative pipelines** · ambitious · CONFIG
  User-defined, phase-based workflows driven entirely by YAML: add, remove or reorder phases, swap handlers and change role routing without touching Python.

- **OpenCode CLI plugin** · ambitious · INTEGRATION
  Integrate AgentMux as a plugin inside the OpenCode CLI so complex tmux-backed multi-agent workflows can be launched natively from the OpenCode ecosystem.

- **IDE adapters (VS Code, Zed)** · ambitious · INTEGRATION
  Separate UI from execution. Editor plugins drive the tmux backend through a local API and visualise the workflow directly inside the IDE, so the terminal no longer has to be in the foreground.

## Horizon

The horizon items are genuinely ambitious. They are the direction, not the next sprint.

- **Cloud handoff** · ambitious · CLOUD
  Checkpoint a running tmux session locally, sync the workspace and resume seamlessly on self-hosted server hardware. Hybrid local and remote execution without losing the deterministic pipeline guarantees.

- **Managed AgentMux** · ambitious · SAAS
  A hosted control plane to run, observe and scale AgentMux pipelines from the browser.
