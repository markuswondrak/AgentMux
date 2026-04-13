---
layout: home

hero:
  name: "AgentMux"
  text: "Multi-agent pipelines,\nno extra subscriptions."
  tagline: "Run a full multi-agent software pipeline using the AI subscriptions you already have."
  actions:
    - theme: brand
      text: Get Started
      link: /docs/getting-started
    - theme: alt
      text: View on GitHub
      link: https://github.com/markuswondrak/AgentMux

features:
  - icon: 💸
    title: No API costs
    details: AgentMux injects prompts into tmux panes — reusing your existing Claude, Codex, Gemini, and OpenCode subscriptions. No pay-per-token.
  - icon: 🔀
    title: Mix providers per role
    details: Assign different AI tools to different roles. Run the architect on Claude Max, the coder on Codex, and the reviewer on Gemini — all in one pipeline.
  - icon: 🏗️
    title: Structured pipeline
    details: A deterministic state machine drives every run — product management, architecting, planning, implementing, reviewing, and completion.
  - icon: 👀
    title: Watch it work
    details: Attach to the tmux session any time. See exactly what each agent is doing, and intervene whenever you want.
  - icon: 🐙
    title: GitHub-native
    details: Bootstrap a pipeline directly from a GitHub issue. AgentMux opens a pull request automatically when the work is complete.
  - icon: ↩️
    title: Resumable
    details: Interrupted runs pick up exactly where they left off — session state is persisted to disk between restarts.
---

<Quickstart />

## Supported providers

`claude` &nbsp;·&nbsp; `codex` &nbsp;·&nbsp; `copilot` &nbsp;·&nbsp; `gemini` &nbsp;·&nbsp; `opencode` &nbsp;·&nbsp; `qwen`

Each provider is configured independently — mix and match per agent role in your `.agentmux/config.yaml`.

---

<details>
<summary>AgentMux logo (ASCII)</summary>

```
╭──────────────────────────────────────────────╮
│   █████╗  ██████╗ ███████╗███╗   ██╗████████╗│
│  ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝│
│  ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   │
│  ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   │
│  ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   │
│  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   │
├──────────────────────────────┬───────────────┤
│ ███╗   ███╗██╗   ██╗██╗  ██╗ │   [ ]──┐      │
│ ████╗ ████║██║   ██║╚██╗██╔╝ │        │      │
│ ██╔████╔██║██║   ██║ ╚███╔╝  │ ──[ ]──◆──[ ] │
│ ██║╚██╔╝██║██║   ██║ ██╔██╗  │        │      │
│ ██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗ │   [ ]──┘      │
│ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝ │               │
╰──────────────────────────────┴───────────────╯
```

</details>
