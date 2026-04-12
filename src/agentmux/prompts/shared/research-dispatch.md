## Research

Before proceeding, assess what you need to know about the codebase or external landscape.

**Look it up yourself** when reading 1–3 specific files whose paths you already know (e.g. checking a function signature, a config schema). Do this directly with your file-reading tool.

**Delegate to code-researcher** for anything requiring broad exploration — tracing a feature across modules, understanding patterns you haven't seen, surveying all usages of something:
1. Call `research_dispatch_code` with your topic, context, `questions=[...]`, `feature_dir="[[placeholder:feature_dir]]"`, and `scope_hints=[...]`.
2. After dispatching, stop and wait idle. Do not poll and do not call a blocking MCP wait tool.
3. AgentMux will send you a follow-up message when research is complete.
4. When that message arrives, read `03_research/code-<topic>/summary.md` first and `03_research/code-<topic>/detail.md` only if needed.

**Delegate to web-researcher** for external information — library APIs, version compatibility, ecosystem best practices:
1. Call `research_dispatch_web` with your topic, context, `questions=[...]`, `feature_dir="[[placeholder:feature_dir]]"`, and `scope_hints=[...]`.
2. After dispatching, stop and wait idle for AgentMux to notify you that the result files are ready.
3. Then read `03_research/web-<topic>/summary.md` first and `03_research/web-<topic>/detail.md` if needed.

You can dispatch multiple topics before going idle. Research tasks run in parallel.

Use a JSON-style array for `scope_hints`, not a single string. Example:
`scope_hints=["agent prompts", "planning tests", "ignore runtime internals"]`

**IMPORTANT:** Do NOT use your built-in tools (web search, code exploration sub-agents, etc.) for research. Use the MCP research dispatch tools above. Your built-in tools bypass the pipeline's agent coordination.
