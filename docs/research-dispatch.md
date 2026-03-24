# Research Task Dispatch

> Related source files: `agentmux/phases.py` (PlanningPhase, ProductManagementPhase), `agentmux/prompts.py`, `agentmux/prompts/agents/code-researcher.md`, `agentmux/prompts/agents/web-researcher.md`

During the planning phase, the architect can request research by writing request files. During the product management phase, the product manager can also request research. Both code-researcher and web-researcher follow the same dispatch pattern.

## Code-researcher

The architect writes `research/code-<topic>/request.md` files (where `<topic>` is a descriptive slug like `auth-module` or `db-schema`). The orchestrator:

1. Detects the new request file
2. Spawns a code-researcher pane (parallel to architect, not exclusive)
3. Injects the research assignment and tracks the topic in `state.json["research_tasks"]`
4. Code-researcher analyzes the codebase and produces:
   - `research/code-<topic>/summary.md` — concise answers for architect
   - `research/code-<topic>/detail.md` — comprehensive analysis for coder/designer
   - `research/code-<topic>/done` — empty completion marker
5. Orchestrator notifies architect when analysis is complete

## Web-researcher

The architect writes `research/web-<topic>/request.md` files (where `<topic>` is a descriptive slug like `nodejs-versions` or `aws-pricing`). The orchestrator:

1. Detects the new request file
2. Spawns a web-researcher pane (parallel to architect, not exclusive)
3. Injects the research assignment and tracks the topic in `state.json["web_research_tasks"]`
4. Web-researcher searches the internet via WebFetch and WebSearch tools and produces:
   - `research/web-<topic>/summary.md` — concise answers with version numbers and source URLs for architect
   - `research/web-<topic>/detail.md` — comprehensive findings with full citations for coder/designer
   - `research/web-<topic>/done` — empty completion marker
5. Orchestrator notifies architect when analysis is complete

## Parallel execution

Multiple research tasks can run in parallel and simultaneously across both types. The architect can continue planning while research is underway and incorporate findings when ready.

Web-researcher is configured to use Sonnet (not Haiku) for better reasoning about sources and precision regarding version numbers and technical specifications.
