from __future__ import annotations

from dataclasses import dataclass

from .models import AgentConfig


@dataclass(frozen=True)
class Provider:
    name: str
    cli: str
    models: dict[str, str]
    trust_snippet: str | None
    default_args: dict[str, list[str]]


PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        name="claude",
        cli="claude",
        models={"max": "opus", "standard": "sonnet", "low": "haiku"},
        trust_snippet="Do you trust the contents of this directory?",
        default_args={
            "architect": [
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Bash(ls:*) Bash(cat:*) Bash(find:*) Bash(grep:*) Bash(git:*) Bash(head:*) Bash(tail:*) Bash(pwd:*) Bash(wc:*)",
            ],
            "coder": ["--permission-mode", "acceptEdits"],
            "designer": ["--permission-mode", "acceptEdits"],
            "docs": ["--permission-mode", "acceptEdits"],
            "code-researcher": [
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Read Glob Grep Write Edit Bash(ls:*) Bash(cat:*) Bash(find:*) Bash(grep:*) Bash(head:*) Bash(tail:*) Bash(pwd:*) Bash(wc:*)",
            ],
            "web-researcher": [
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "WebFetch WebSearch Read Glob Grep Write Edit Bash(ls:*) Bash(cat:*) Bash(head:*) Bash(tail:*)",
            ],
        },
    ),
    "codex": Provider(
        name="codex",
        cli="codex",
        models={
            "max": "gpt-5.4-codex-medium",
            "standard": "gpt-5.3-codex-high",
            "low": "gpt-5.2-codex",
        },
        trust_snippet=None,
        default_args={
            "architect": ["-s", "workspace-write", "-a", "never"],
            "coder": ["-s", "workspace-write", "-a", "never"],
            "designer": ["-s", "workspace-write", "-a", "never"],
            "docs": ["-s", "workspace-write", "-a", "never"],
            "code-researcher": ["-s", "workspace-write", "-a", "never"],
            "web-researcher": ["-s", "workspace-write", "-a", "never"],
        },
    ),
    "gemini": Provider(
        name="gemini",
        cli="gemini",
        models={
            "max": "gemini-2.5-pro",
            "standard": "gemini-2.5-flash",
            "low": "gemini-2.5-flash-lite",
        },
        trust_snippet="Trust this folder?",
        default_args={
            "architect": ["--approval-mode", "yolo"],
            "coder": ["--approval-mode", "yolo"],
            "designer": ["--approval-mode", "yolo"],
            "docs": ["--approval-mode", "yolo"],
            "code-researcher": ["--approval-mode", "yolo"],
            "web-researcher": ["--approval-mode", "yolo"],
        },
    ),
    "opencode": Provider(
        name="opencode",
        cli="opencode",
        models={
            "max": "anthropic/claude-opus-4-6",
            "standard": "anthropic/claude-sonnet-4-20250514",
            "low": "anthropic/claude-haiku-4-5-20251001",
        },
        trust_snippet=None,
        default_args={
            "architect": [],
            "coder": [],
            "designer": [],
            "docs": [],
            "code-researcher": [],
            "web-researcher": [],
        },
    ),
}


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"Unknown provider '{name}'. Expected one of: {available}") from exc


def resolve_agent(global_provider: Provider, role: str, role_config: dict) -> AgentConfig:
    provider_name = role_config.get("provider")
    provider = get_provider(provider_name) if provider_name else global_provider

    tier = str(role_config.get("tier", "standard"))
    try:
        model = provider.models[tier]
    except KeyError as exc:
        valid_tiers = ", ".join(sorted(provider.models))
        raise ValueError(
            f"Unknown tier '{tier}' for provider '{provider.name}'. Expected one of: {valid_tiers}"
        ) from exc

    args = role_config.get("args")
    if args is None:
        args = provider.default_args.get(role, [])

    return AgentConfig(
        role=role,
        cli=provider.cli,
        model=model,
        args=list(args),
        trust_snippet=provider.trust_snippet,
    )
