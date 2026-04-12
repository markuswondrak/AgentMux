from __future__ import annotations

import shlex

from ..shared.models import AgentConfig, BatchCommandMode


def build_agent_command(agent: AgentConfig, prompt_file: str | None = None) -> str:
    """Build the shell command for an agent pane.

    For batch-mode agents (e.g. researchers), pass ``prompt_file`` to append
    it according to ``agent.batch_command.mode``:

    - ``POSITIONAL``: prompt file as last positional argument
    - ``FLAG``: prompt file directly after the flag (e.g. ``-p``)
    - ``STDIN``: prompt file via stdin redirect (``< prompt.md``)

    The ``--model`` flag is only included when ``agent.model_flag`` is not
    ``None``.  Providers like opencode that ignore model settings should set
    ``model_flag=None`` in their provider config.
    """
    env_prefix = ""
    if agent.env:
        env_items = [
            f"{shlex.quote(str(key))}={shlex.quote(str(value))}"
            for key, value in agent.env.items()
        ]
        env_prefix = f"env {' '.join(env_items)} "

    cli_segment = _build_cli_segment(agent, prompt_file)

    if agent.model_flag is not None:
        model_segment = f" {shlex.quote(agent.model_flag)} {shlex.quote(agent.model)}"
    else:
        model_segment = ""

    extra_args = " ".join(shlex.quote(a) for a in (agent.args or []))

    cmd = (
        env_prefix
        + cli_segment
        + model_segment
        + (f" {extra_args}" if extra_args else "")
    )

    # For POSITIONAL mode or no batch_command, append prompt file at the end
    if prompt_file is not None:
        if agent.batch_command is not None:
            if agent.batch_command.mode is BatchCommandMode.POSITIONAL:
                cmd += f" {shlex.quote(prompt_file)}"
            elif agent.batch_command.mode is BatchCommandMode.STDIN:
                cmd += f" < {shlex.quote(prompt_file)}"
        else:
            # No batch_command: default behaviour – append as positional
            cmd += f" {shlex.quote(prompt_file)}"

    return cmd


def _build_cli_segment(agent: AgentConfig, prompt_file: str | None) -> str:
    """Build the CLI portion of the command based on batch_command mode."""
    batch_cmd = agent.batch_command

    # No batch command or no prompt file: just the CLI
    if batch_cmd is None or prompt_file is None:
        return shlex.quote(agent.cli)

    verb_quoted = shlex.quote(batch_cmd.verb)
    cli_quoted = shlex.quote(agent.cli)
    prompt_quoted = shlex.quote(prompt_file)

    if batch_cmd.mode is BatchCommandMode.FLAG:
        # Flag-style: cli -p prompt.md
        return f"{cli_quoted} {verb_quoted} {prompt_quoted}"
    elif batch_cmd.mode is BatchCommandMode.STDIN:
        # Stdin redirect: cli (optional verb)
        # Actual redirect (< prompt.md) is appended later
        if batch_cmd.verb:
            return f"{cli_quoted} {verb_quoted}"
        return cli_quoted
    else:
        # POSITIONAL: cli verb (prompt appended later in build_agent_command)
        return f"{cli_quoted} {verb_quoted}"
