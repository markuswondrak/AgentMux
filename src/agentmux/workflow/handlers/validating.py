"""Event-driven handler for automated validation between implementation and review."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentmux.workflow.event_catalog import (
    EVENT_RESUMED,
    EVENT_VALIDATION_FAILED,
    EVENT_VALIDATION_PASSED,
)
from agentmux.workflow.event_router import EventSpec, WorkflowEvent
from agentmux.workflow.phase_result import PhaseResult

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext

ROLE_NAME = "validating"


def _validation_result_ready(path: str, ctx: PipelineContext, state: dict) -> bool:
    full = ctx.files.feature_dir / path
    if not full.exists():
        return False
    try:
        data = json.loads(full.read_text(encoding="utf-8").strip())
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and "passed" in data


_SPECS = (
    EventSpec(
        name="validation_result",
        watch_paths=("06_implementation/validation_result.json",),
        is_ready=_validation_result_ready,
    ),
)


class ValidatingHandler:
    """Runs configured validation commands (or fast-paths when unset)."""

    def enter(self, state: dict, ctx: PipelineContext) -> PhaseResult:
        commands = ctx.workflow_settings.validation.commands
        result_path = ctx.files.implementation_dir / "validation_result.json"

        if not commands:
            return PhaseResult({}, next_phase="reviewing")

        if result_path.exists() and state.get("last_event") == EVENT_RESUMED:
            data = self._read_result_payload(result_path)
            if data is not None:
                updates, next_phase = self._apply_validation_payload(state, ctx, data)
                return PhaseResult(updates, next_phase=next_phase)

        if result_path.exists():
            result_path.unlink()

        project_dir = ctx.files.project_dir
        cmd = (
            f"{shlex.quote(sys.executable)} -m agentmux.workflow.validation "
            f"--project-dir {shlex.quote(str(project_dir))} "
            f"--result-path {shlex.quote(str(result_path))} "
            f"--cwd {shlex.quote(str(project_dir))}"
        )
        ctx.runtime.run_validation_pane(cmd, "Validating")
        return PhaseResult({})

    def get_event_specs(self) -> tuple[EventSpec, ...]:
        return _SPECS

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: PipelineContext,
    ) -> tuple[dict, str | None]:
        if event.kind != "validation_result":
            return {}, None
        result_path = ctx.files.implementation_dir / "validation_result.json"
        data = self._read_result_payload(result_path)
        if data is None:
            return {}, None
        return self._apply_validation_payload(state, ctx, data)

    @staticmethod
    def _read_result_payload(result_path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8").strip())
        except (OSError, json.JSONDecodeError):
            return None
        return raw if isinstance(raw, dict) else None

    def _apply_validation_payload(
        self,
        state: dict,
        ctx: PipelineContext,
        data: dict[str, Any],
    ) -> tuple[dict, str | None]:
        passed = data.get("passed")
        if passed is True:
            status_path = ctx.files.review_dir / "validation_status.md"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                "## Automated Validation\n\n"
                "All configured validation commands passed.\n",
                encoding="utf-8",
            )
            return {"last_event": EVENT_VALIDATION_PASSED}, "reviewing"

        if passed is False:
            failed_command = str(data.get("failed_command") or "")
            tail_output = str(data.get("tail_output") or "")
            full_output = str(data.get("full_output") or "")
            log_path = ctx.files.review_dir / "validation_failure.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(full_output, encoding="utf-8")

            next_iteration = int(state.get("review_iteration", 0)) + 1
            fix_body = (
                "Automated validation failed.\n\n"
                f"Command: `{failed_command}`\n\n"
                f"Tail output:\n```\n{tail_output}\n```\n\n"
                f"Full output was written to "
                f"`{(ctx.files.relative_path(log_path))}`.\n"
            )
            ctx.files.fix_request.parent.mkdir(parents=True, exist_ok=True)
            ctx.files.fix_request.write_text(fix_body, encoding="utf-8")
            return (
                {
                    "last_event": EVENT_VALIDATION_FAILED,
                    "review_iteration": next_iteration,
                },
                "fixing",
            )

        return {}, None
