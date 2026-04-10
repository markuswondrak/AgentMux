# Phase: Product Management

> Related source files: `src/agentmux/workflow/handlers/product_management.py`, `src/agentmux/workflow/phase_registry.py`, `src/agentmux/workflow/prompts.py`, `src/agentmux/integrations/mcp_server.py`
> Directory: `01_product_management/` | Optional: yes (requires `--product-manager` flag)

The product manager analyzes the feature request for usability concerns, integration fit, and design trade-offs before the architect begins technical planning. The product manager clarifies requirements through discussion — updated requirements are written directly to `requirements.md`.

## Conditions

Activated only when the pipeline is started with the `--product-manager` flag (or `agentmux issue ... --product-manager`). Skipped entirely otherwise; the pipeline starts directly at `architecting`.

## Role

**product-manager** agent — analyzes requirements and produces advisory analysis.

## Artifacts

| File | Writer | Reader | Format |
|------|--------|--------|--------|
| `product_manager_prompt.md` | orchestrator | product-manager agent | Markdown prompt |
| `requirements.md` | product-manager agent | architect | Updated requirements |
| `done` | product-manager agent (via `submit_pm_done`) | orchestrator | empty marker |

## Transitions

| From | Event | To |
|------|-------|----|
| *(pipeline start with `--product-manager`)* | — | `product_management` |
| `product_management` | `pm_completed` (on `done` written) | `architecting` |

## Notes

- The monitor shows this phase only when it is active (optional phase).
