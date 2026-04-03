from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from ..configuration import load_builtin_catalog, load_layered_config
from ..integrations.mcp import McpServerSpec, ensure_mcp_config
from ..terminal_ui.colors import QUESTIONARY_SECONDARY
from ..terminal_ui.screens import render_logo

try:
    import questionary
    from questionary import Style
except ImportError:  # pragma: no cover - optional at import time in this environment
    questionary = None

    class Style(list):  # type: ignore[no-redef]
        pass


try:
    from rich.console import Console
    from rich.rule import Rule
except ImportError:  # pragma: no cover - optional at import time in this environment
    Console = None  # type: ignore[assignment]
    Rule = None  # type: ignore[assignment]


KNOWN_PROVIDERS = ("claude", "codex", "gemini", "opencode", "copilot")
PROMPTED_ROLES = ("architect", "product-manager", "reviewer", "coder", "designer")
PROMPT_STUB_ROLES = ("coder", "reviewer", "architect", "product-manager", "designer")

INIT_STYLE = Style(
    [
        ("qmark", "fg:ansigreen bold"),
        ("question", "bold"),
        ("answer", f"fg:{QUESTIONARY_SECONDARY} bold"),
        ("pointer", f"fg:{QUESTIONARY_SECONDARY} bold"),
        ("highlighted", f"fg:{QUESTIONARY_SECONDARY} bold"),
        ("selected", "fg:ansigreen"),
        ("separator", "fg:ansiyellow"),
        ("instruction", "fg:ansiyellow"),
    ]
)

CLAUDE_TEMPLATE = """# {project_name}

## Build Command
`TODO: add your build command`

## Test Command
`TODO: add your test command`

## Lint Command
`TODO: add your lint command`

## Architecture
`TODO: describe the project architecture`

## Key Conventions
`TODO: document conventions this project follows`
"""

STUB_TEMPLATES = {
    "coder": """<!-- Project-specific instructions for the coder role. -->
- Example: Use `pytest` for tests and keep changes scoped to requested files.
""",
    "reviewer": """<!-- Project-specific instructions for the reviewer role. -->
- Example: Check type annotations and call out behavioral regressions first.
""",
    "architect": """<!-- Project-specific instructions for the architect role. -->
- Example: Keep plan steps executable and aligned with existing module boundaries.
""",
    "product-manager": """\
<!-- Project-specific instructions for the product-manager role. -->
- Example: Make acceptance criteria explicit and testable before implementation.
""",
    "designer": """<!-- Project-specific instructions for the designer role. -->
- Example: Prefer consistent visual hierarchy and responsive spacing tokens.
""",
}


class _PlainConsole:
    def print(self, *objects: object, **_kwargs: object) -> None:
        print(" ".join(str(item) for item in objects))

    def rule(self, title: object = "") -> None:
        print(str(title))


def _console(console: Any | None) -> Any:
    if console is not None:
        return console
    if Console is None:
        return _PlainConsole()
    return Console()


def _detect_shell() -> tuple[str, Path]:
    """Detect user's shell and return shell type and config file path."""
    shell_path = os.environ.get("SHELL", "")
    shell_name = Path(shell_path).name if shell_path else "bash"

    home = Path.home()

    if shell_name in ("bash", "sh"):
        # Prefer .bashrc, fall back to .bash_profile or .profile
        candidates = [home / ".bashrc", home / ".bash_profile", home / ".profile"]
        for candidate in candidates:
            if candidate.exists():
                return ("bash", candidate)
        return ("bash", home / ".bashrc")  # Default to .bashrc

    elif shell_name == "zsh":
        config_file = home / ".zshrc"
        # Check for ZDOTDIR
        zdotdir = os.environ.get("ZDOTDIR")
        if zdotdir:
            config_file = Path(zdotdir) / ".zshrc"
        return ("zsh", config_file)

    else:
        # Unknown shell, return generic config
        return (shell_name, home / f".{shell_name}rc")


def _is_completion_enabled(config_path: Path, shell: str) -> bool:
    """Check if agentmux completions are already enabled in shell config."""
    if not config_path.exists():
        return False

    try:
        content = config_path.read_text(encoding="utf-8")
        # Check for common patterns
        patterns = [
            r"eval.*agentmux\s+completions\s+(bash|zsh)",
            r"agentmux\s+completions\s+(bash|zsh)",
        ]
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
    except Exception:
        return False


def _enable_completions(config_path: Path, shell: str) -> bool:
    """Add agentmux completion setup to shell config file."""
    try:
        # Read existing content to check for trailing newline
        existing_content = ""
        if config_path.exists():
            existing_content = config_path.read_text(encoding="utf-8")

        # Append the completion setup
        completion_line = (
            f'eval "$(agentmux completions {shell})"  # agentmux shell completions'
        )

        # Build new content
        new_content = existing_content
        # Add newline if file doesn't end with one (and has content)
        if existing_content and not existing_content.endswith("\n"):
            new_content += "\n"

        new_content += "\n# AgentMux Shell Completions\n"
        new_content += f"{completion_line}\n"

        config_path.write_text(new_content, encoding="utf-8")
        return True
    except Exception:
        return False


def prompt_shell_completions(console: Any | None = None) -> tuple[bool, str]:
    """Prompt user to enable shell completions."""
    output = _console(console)

    shell_type, config_path = _detect_shell()

    if _is_completion_enabled(config_path, shell_type):
        output.print(
            f"[dim]Shell completions already enabled in {config_path.name}[/dim]"
        )
        return (True, "already-enabled")

    # Only support bash and zsh
    if shell_type not in ("bash", "zsh"):
        output.print(f"[dim]Shell completion not supported for {shell_type}[/dim]")
        return (False, "unsupported-shell")

    # Prompt user
    enable = _confirm(f"Enable shell completions for {shell_type}?", default=True)

    if enable:
        if _enable_completions(config_path, shell_type):
            output.print(f"[green]✓[/green] Added completions to {config_path}")
            output.print(f"  Restart your shell or run: source {config_path}")
            return (True, "enabled")
        else:
            output.print(f"[red]✗[/red] Failed to modify {config_path}")
            return (False, "failed")
    else:
        output.print(
            "[dim]Skipped shell completions (run 'agentmux completions "
            f"{shell_type}' to see instructions)[/dim]"
        )
        return (False, "skipped")


def _rule(title: str) -> object:
    if Rule is None:
        return title
    return Rule(title, style="bold white")


def _require_questionary() -> Any:
    if questionary is None:
        raise SystemExit(
            "Missing dependency: questionary. "
            "Install with `python3 -m pip install -r requirements.txt`."
        )
    return questionary


def _select(message: str, choices: list[str], default: str | None = None) -> str:
    q = _require_questionary()
    answer = q.select(message, choices=choices, default=default, style=INIT_STYLE).ask()
    return str(
        answer if answer is not None else default if default is not None else choices[0]
    )


def _text(message: str, default: str = "") -> str:
    q = _require_questionary()
    answer = q.text(message, default=default, style=INIT_STYLE).ask()
    return str(answer if answer is not None else default)


def _confirm(message: str, default: bool = False) -> bool:
    q = _require_questionary()
    answer = q.confirm(message, default=default, style=INIT_STYLE).ask()
    return bool(default if answer is None else answer)


def _merge_overrides(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_overrides(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _detect_git_base_branch(default: str) -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "show", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return default

    output = result.stdout or ""
    for line in output.splitlines():
        if "HEAD branch:" not in line:
            continue
        branch = line.split("HEAD branch:", 1)[1].strip()
        if branch:
            return branch
    return default


def _claude_md_content(project_dir: Path) -> str:
    return CLAUDE_TEMPLATE.format(project_name=project_dir.name)


def _stub_path(project_dir: Path, role: str) -> Path:
    from ..shared.models import ProjectPaths

    paths = ProjectPaths.from_project(project_dir)
    return paths.agent_prompts_dir / f"{role}.md"


def detect_clis() -> dict[str, bool]:
    return {
        provider: shutil.which(provider) is not None for provider in KNOWN_PROVIDERS
    }


def display_detection(console: Any | None, detected: dict[str, bool]) -> None:
    output = _console(console)
    parts = ["[bold white]Detected CLI tools:[/bold white]"]
    for provider in KNOWN_PROVIDERS:
        if detected.get(provider, False):
            parts.append(f"{provider} [green]✓[/green]")
        else:
            parts.append(f"{provider} [dim red]✗[/dim red]")
    output.print("  ".join(parts))


def prompt_role_config(
    detected_providers: list[str], defaults_config: dict[str, Any]
) -> dict[str, Any]:
    if not detected_providers:
        raise SystemExit(
            "No supported provider CLI detected. "
            "Install one of: claude, codex, gemini, opencode, copilot."
        )

    defaults = dict(defaults_config.get("defaults", {}))
    role_defaults = dict(defaults_config.get("roles", {}))
    builtin_default_provider = str(defaults.get("provider", "claude"))
    builtin_default_model = str(defaults.get("model", "sonnet"))
    selected_default = _select(
        "Default provider",
        detected_providers,
        default=builtin_default_provider
        if builtin_default_provider in detected_providers
        else detected_providers[0],
    )
    setup_mode = _select(
        "Role setup",
        ["Use default provider for all roles", "Customize roles"],
        default="Use default provider for all roles",
    )

    result: dict[str, Any] = {}
    defaults_override: dict[str, Any] = {}
    if selected_default != builtin_default_provider:
        defaults_override["provider"] = selected_default
    if defaults_override:
        result["defaults"] = defaults_override

    if setup_mode == "Use default provider for all roles":
        roles_override: dict[str, Any] = {}
        for role, role_cfg_raw in role_defaults.items():
            role_cfg = dict(role_cfg_raw) if isinstance(role_cfg_raw, dict) else {}
            baseline_provider = str(role_cfg.get("provider", selected_default))
            if baseline_provider != selected_default:
                roles_override[role] = {"provider": selected_default}
        if roles_override:
            result["roles"] = roles_override
        return result

    roles_override: dict[str, Any] = {}
    for role in PROMPTED_ROLES:
        role_cfg = (
            dict(role_defaults.get(role, {}))
            if isinstance(role_defaults.get(role), dict)
            else {}
        )
        baseline_provider = str(role_cfg.get("provider", selected_default))
        baseline_model = str(role_cfg.get("model", builtin_default_model))
        provider_prompt_default = str(role_cfg.get("provider", "default"))
        if (
            provider_prompt_default != "default"
            and provider_prompt_default not in detected_providers
        ):
            provider_prompt_default = "default"

        selected_provider = _select(
            f"{role}: provider",
            ["default", *detected_providers],
            default=provider_prompt_default,
        )
        selected_model = _text(
            f"{role}: model",
            default=baseline_model,
        )

        effective_provider = (
            selected_default if selected_provider == "default" else selected_provider
        )
        effective_model = selected_model if selected_model else baseline_model
        role_override: dict[str, str] = {}
        if effective_provider != baseline_provider:
            role_override["provider"] = effective_provider
        if effective_model != baseline_model:
            role_override["model"] = effective_model
        if role_override:
            roles_override[role] = role_override

    if roles_override:
        result["roles"] = roles_override

    return result


def prompt_github_settings(
    defaults_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults_source = (
        defaults_config if defaults_config is not None else load_builtin_catalog()
    )
    github_defaults = dict(defaults_source.get("github", {}))

    default_base_branch = str(github_defaults.get("base_branch", "main"))
    default_draft = bool(github_defaults.get("draft", True))
    default_prefix = str(github_defaults.get("branch_prefix", "feature/"))

    detected_base = _detect_git_base_branch(default_base_branch)
    base_branch = _text("Base branch", default=detected_base)
    draft_choice = _select(
        "Create draft PRs by default?",
        ["yes", "no"],
        default="yes" if default_draft else "no",
    )
    branch_prefix = _text("Branch prefix", default=default_prefix)

    github_override: dict[str, Any] = {}
    if base_branch != default_base_branch:
        github_override["base_branch"] = base_branch
    draft_value = draft_choice == "yes"
    if draft_value != default_draft:
        github_override["draft"] = draft_value
    if branch_prefix != default_prefix:
        github_override["branch_prefix"] = branch_prefix

    if github_override:
        return {"github": github_override}
    return {}


def prompt_claude_md(
    project_dir: Path, console: Any | None = None
) -> tuple[list[Path], list[Path]]:
    output = _console(console)
    q = _require_questionary()
    target = project_dir / "CLAUDE.md"

    if target.exists():
        output.print(
            "[yellow]CLAUDE.md already exists. Replacing or symlinking will "
            "overwrite the current file.[/yellow]"
        )
        choice = q.select(
            "CLAUDE.md setup",
            choices=[
                "Keep existing",
                "Replace with template",
                "Symlink existing file",
                "Skip",
            ],
            default="Keep existing",
            style=INIT_STYLE,
        ).ask()
    else:
        choice = q.select(
            "CLAUDE.md setup",
            choices=[
                "Create new from template",
                "Symlink existing file",
                "Skip",
            ],
            default="Create new from template",
            style=INIT_STYLE,
        ).ask()

    choice_label = str(choice or "Skip")
    created: list[Path] = []
    skipped: list[Path] = []

    if choice_label in {"Keep existing", "Skip"}:
        skipped.append(target)
        return created, skipped

    if choice_label in {"Create new from template", "Replace with template"}:
        target.write_text(_claude_md_content(project_dir), encoding="utf-8")
        created.append(target)
        return created, skipped

    path_prompt = getattr(q, "path", None)
    if callable(path_prompt):
        source = path_prompt("Path to existing file", style=INIT_STYLE).ask()
    else:
        source = q.text("Path to existing file", style=INIT_STYLE).ask()

    if not source:
        skipped.append(target)
        return created, skipped

    source_path = Path(str(source)).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(
            f"Cannot create symlink; source path does not exist: {source_path}"
        )

    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(source_path)
    created.append(target)
    return created, skipped


def prompt_stubs(project_dir: Path, console: Any | None = None) -> list[str]:
    output = _console(console)
    q = _require_questionary()

    existing = [
        role for role in PROMPT_STUB_ROLES if _stub_path(project_dir, role).exists()
    ]
    if existing:
        output.print(
            f"[dim]Prompt stubs already exist and will be skipped: "
            f"{', '.join(existing)}[/dim]"
        )

    available = [role for role in PROMPT_STUB_ROLES if role not in existing]
    if not available:
        return []

    choices = [q.Choice(role, checked=(role == "coder")) for role in available]
    selected = q.checkbox(
        "Select prompt stubs to create",
        choices=choices,
        style=INIT_STYLE,
    ).ask()
    if not selected:
        return []
    return [str(role) for role in selected]


def generate_config(
    overrides: dict[str, Any],
    project_dir: Path,
    console: Any | None = None,
    defaults_mode: bool = False,
) -> Path:
    from ..shared.models import ProjectPaths

    _ = _console(console)
    paths = ProjectPaths.from_project(project_dir)
    config_path = paths.config
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists() and not defaults_mode:
        should_overwrite = _confirm(
            "`.agentmux/config.yaml` already exists. Overwrite it?", default=False
        )
        if not should_overwrite:
            raise SystemExit(
                "Aborted. Existing .agentmux/config.yaml was not overwritten."
            )

    data: dict[str, Any] = {"version": 2}
    for section in ("defaults", "roles", "github"):
        section_data = overrides.get(section)
        if isinstance(section_data, dict) and section_data:
            data[section] = section_data

    rendered = yaml.safe_dump(data, sort_keys=False)
    config_path.write_text(rendered, encoding="utf-8")
    return config_path


def validate_config(project_dir: Path, console: Any | None = None) -> bool:
    output = _console(console)
    try:
        load_layered_config(project_dir)
    except Exception as exc:
        output.print(f"[red]✗[/red] Config validation failed: {exc}")
        return False

    output.print("[green]✓[/green] Config validates OK")
    return True


def display_summary(
    console: Any | None,
    created_files: list[Path],
    skipped_files: list[Path],
    project_dir: Path,
    completion_status: tuple[bool, str] = (False, ""),
) -> None:
    output = _console(console)
    output.print(_rule("Done"))
    for path in created_files:
        output.print(
            f"[green]✓[/green] Created [yellow]{_relative(path, project_dir)}[/yellow]"
        )
    for path in skipped_files:
        output.print(
            f"[dim]• {_relative(path, project_dir)} already exists, skipped[/dim]"
        )

    # Show completion status
    enabled, status = completion_status
    if status == "enabled":
        output.print(
            "[green]✓[/green] Shell completions enabled (restart shell to use)"
        )
    elif status == "already-enabled":
        output.print("[green]✓[/green] Shell completions already enabled")
    elif status == "skipped":
        output.print("[dim]• Shell completions skipped[/dim]")
    elif status == "unsupported-shell":
        output.print("[dim]• Shell completions not supported for your shell[/dim]")

    output.print('[green]✓[/green] Ready to run: [bold]agentmux "your feature"[/bold]')


def _write_stub(project_dir: Path, role: str) -> Path:
    target = _stub_path(project_dir, role)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(STUB_TEMPLATES[role], encoding="utf-8")
    return target


def _parse_init_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="agentmux init")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Run non-interactively with built-in defaults.",
    )
    return parser.parse_args(argv)


def run_init(defaults_mode: bool = False) -> int:
    project_dir = Path.cwd().resolve()
    output = _console(None)

    render_logo(output)
    detected = detect_clis()
    display_detection(output, detected)

    defaults_config = load_builtin_catalog()
    overrides: dict[str, Any] = {}
    created_files: list[Path] = []
    skipped_files: list[Path] = []

    detected_providers = [
        provider for provider, is_present in detected.items() if is_present
    ]

    if not defaults_mode:
        if not sys.stdin.isatty():
            raise SystemExit(
                "Interactive init requires a TTY. Use `agentmux init --defaults`."
            )
        if not detected_providers:
            raise SystemExit(
                "No supported provider CLI detected. "
                "Install one of: claude, codex, gemini, opencode, copilot."
            )
        output.print(_rule("Role Configuration"))
        role_overrides = prompt_role_config(detected_providers, defaults_config)
        overrides = _merge_overrides(overrides, role_overrides)

        output.print(_rule("GitHub Settings"))
        github_overrides = prompt_github_settings(defaults_config)
        overrides = _merge_overrides(overrides, github_overrides)

    config_path = generate_config(
        overrides, project_dir, output, defaults_mode=defaults_mode
    )
    created_files.append(config_path)

    claude_path = project_dir / "CLAUDE.md"
    if defaults_mode:
        if claude_path.exists():
            skipped_files.append(claude_path)
        else:
            claude_path.write_text(_claude_md_content(project_dir), encoding="utf-8")
            created_files.append(claude_path)
    else:
        output.print(_rule("Project Setup"))
        claude_created, claude_skipped = prompt_claude_md(project_dir, output)
        created_files.extend(claude_created)
        skipped_files.extend(claude_skipped)

        selected_roles = prompt_stubs(project_dir, output)
        for role in selected_roles:
            stub_target = _stub_path(project_dir, role)
            if stub_target.exists():
                skipped_files.append(stub_target)
                continue
            created_files.append(_write_stub(project_dir, role))

    if not validate_config(project_dir, output):
        raise SystemExit(1)

    if not defaults_mode:
        loaded = load_layered_config(project_dir)
        ensure_mcp_config(
            loaded.agents,
            [
                McpServerSpec(
                    name="agentmux-research",
                    module="agentmux.integrations.mcp_research_server",
                    env={},
                )
            ],
            ("architect", "product-manager"),
            project_dir,
            interactive=True,
            output=sys.stdout,
        )

        output.print(_rule("Shell Completions"))
        completion_status = prompt_shell_completions(output)
    else:
        completion_status = (False, "skipped")

    display_summary(
        output, created_files, skipped_files, project_dir, completion_status
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parsed = _parse_init_args(sys.argv[1:] if argv is None else argv)
    return run_init(defaults_mode=bool(parsed.defaults))
