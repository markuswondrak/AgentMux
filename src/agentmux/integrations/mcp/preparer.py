from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TextIO

try:
    import questionary
except ImportError:  # pragma: no cover - optional at import time in this environment
    questionary = None

from ...shared.models import AgentConfig
from .configurators import (
    _required_configurators,
    _server_entry_matches,
)
from .models import McpServerSpec
from .runtime import setup_mcp as _setup_mcp


def _default_confirm(message: str, default: bool = True) -> bool:
    if questionary is not None:
        answer = questionary.confirm(message, default=default).ask()
        return bool(default if answer is None else answer)
    suffix = " [Y/n] " if default else " [y/N] "
    answer = input(message + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def ensure_mcp_config(
    agents: dict[str, AgentConfig],
    servers: list[McpServerSpec],
    roles: Iterable[str],
    project_dir: Path,
    *,
    interactive: bool | None = None,
    output: TextIO | None = None,
    confirm: Callable[[str], bool] | None = None,
) -> None:
    """Ensure provider-native MCP config exists for the selected roles."""

    if interactive is None:
        interactive = sys.stdin.isatty()
    writer = output or sys.stdout
    ask = confirm or _default_confirm

    if not servers:
        return

    configurators = _required_configurators(agents, roles)
    for server in servers:
        for _provider, (configurator, provider_roles) in configurators.items():
            # Check if server exists and matches expected config
            if _server_entry_matches(configurator, server, project_dir):
                # Entry exists and is correct, skip install
                continue

            if configurator.has_server(server, project_dir):
                # Entry exists but differs, install to refresh
                configurator.install(server, project_dir)
                continue

            roles_label = ", ".join(provider_roles)
            if not interactive:
                print(
                    configurator.missing_message(server, project_dir, roles_label),
                    file=writer,
                )
                continue

            message = configurator.prompt_message(server, project_dir, roles_label)
            if ask(message):
                configurator.install(server, project_dir)
                print(configurator.configured_message(server, project_dir), file=writer)
            else:
                print(configurator.skipped_message(server), file=writer)


class McpAgentPreparer:
    def __init__(self, project_dir: Path, *, interactive: bool, output: TextIO) -> None:
        self.project_dir = project_dir
        self.interactive = interactive
        self.output = output

    def ensure_project_config(self, agents: dict[str, AgentConfig]) -> None:
        from .models import DEFAULT_RESEARCH_ROLES, DEFAULT_RESEARCH_SERVERS

        ensure_mcp_config(
            agents,
            list(DEFAULT_RESEARCH_SERVERS),
            DEFAULT_RESEARCH_ROLES,
            self.project_dir,
            interactive=self.interactive,
            output=self.output,
        )

    def prepare_feature_agents(
        self, agents: dict[str, AgentConfig], feature_dir: Path
    ) -> dict[str, AgentConfig]:
        from .models import DEFAULT_RESEARCH_ROLES, DEFAULT_RESEARCH_SERVERS

        return _setup_mcp(
            agents,
            list(DEFAULT_RESEARCH_SERVERS),
            list(DEFAULT_RESEARCH_ROLES),
            feature_dir,
            self.project_dir,
        )
