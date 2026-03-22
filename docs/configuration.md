# Agent Configuration and Provider Abstraction

> Related source files: `src/providers.py`, `src/models.py`, `pipeline_config.json`

## pipeline_config.json

Configuration specifies providers and tier levels (rather than explicit CLI tools and models), allowing roles to use different AI backends and capability levels:

```json
{
  "session_name": "multi-agent-mvp",
  "provider": "claude",
  "max_review_iterations": 3,
  "architect": { "tier": "max" },
  "product-manager": { "tier": "max" },
  "reviewer": { "tier": "standard" },
  "coder": { "provider": "codex", "tier": "standard" },
  "designer": { "tier": "standard" },
  "docs": { "tier": "low" },
  "code-researcher": { "tier": "low" },
  "web-researcher": { "tier": "standard" }
}
```

**Configuration keys:**
- `provider` (top-level): default provider for all roles — defaults to `"claude"`; supported providers are `"claude"`, `"codex"`, `"gemini"`, `"opencode"`
- Per-role `provider` (optional): overrides the global provider for that role
- `tier` (per role): `"max"` / `"standard"` / `"low"` — resolved to a concrete model by the provider
- `args` (per role, optional): overrides the provider's default CLI arguments for that role
- `max_review_iterations` caps automatic reviewer→coder fix loops before forcing user confirmation

## CLI flags

- `--product-manager` enables the `product_management` phase before planning.
- When enabled, initial pipeline phase is `product_management` and state stores `"product_manager": true`.

## Tier-to-model mapping

| Tier | claude | codex | gemini | opencode |
|------|--------|-------|--------|----------|
| max | `opus` | `gpt-5.4` | `gemini-2.5-pro` | `anthropic/claude-opus-4-6` |
| standard | `sonnet` | `gpt-5.3-codex` | `gemini-2.5-flash` | `anthropic/claude-sonnet-4-20250514` |
| low | `haiku` | `gpt-5.1-mini` | `gemini-2.5-flash-lite` | `anthropic/claude-haiku-4-5-20251001` |

The orchestrator never calls the AI APIs directly; it always goes through these CLI tools, looking up the appropriate model via provider configuration.

## Provider dataclass

- `name` — identifier (`"claude"`, `"codex"`, `"gemini"`, `"opencode"`)
- `cli` — binary name (e.g., `"claude"`, `"codex"`)
- `models` — dict mapping tier (`"max"`, `"standard"`, `"low"`) to model name
- `trust_snippet` — text to detect for auto-accept (e.g., `"Do you trust the contents of this directory?"`), or `None` if no trust prompt
- `default_args` — dict mapping role name to default CLI argument list

## Tier resolution

The `resolve_agent(global_provider, role, role_config)` function:
1. Determines effective provider: uses `role_config.get("provider")` if specified, otherwise falls back to global `provider`
2. Looks up the `Provider` from the `PROVIDERS` registry
3. Resolves the `tier` to a concrete model name via `provider.models[tier]`
4. Resolves CLI args: uses `role_config.get("args")` if present, otherwise `provider.default_args.get(role, [])`
5. Returns an `AgentConfig` with the resolved cli, model, args, and trust_snippet

This allows configuration changes (switching providers, adjusting tiers) without modifying agent implementation code.
