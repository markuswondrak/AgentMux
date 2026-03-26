from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .interruption_events import (
    INTERRUPTION_CATEGORY_FAILED,
    canonical_event_for_category,
    canonical_interruption_event,
    fallback_cause_for_category,
    fallback_cause_from_event,
    interruption_category_from_event,
    interruption_title_for_category,
    normalize_interruption_category,
)
from .state import update_phase

InterruptionCategory = Literal["canceled", "failed"]


@dataclass(frozen=True)
class InterruptionReport:
    category: InterruptionCategory
    cause: str
    resume_command: str
    log_path: str | None
    last_event: str


class InterruptionService:
    def report_from_state(self, state: dict[str, Any], feature_dir: Path, *, files=None) -> InterruptionReport | None:
        raw_category = normalize_interruption_category(state.get("interruption_category"))
        raw_cause = self._coalesce_text(state.get("interruption_cause", ""))
        raw_resume = str(state.get("interruption_resume_command", "")).strip()
        raw_log_value = state.get("interruption_log_path")
        raw_log = None
        if isinstance(raw_log_value, str):
            raw_log = raw_log_value.strip() or None
        last_event = str(state.get("last_event", "")).strip()

        category: InterruptionCategory | None = raw_category
        if category is None:
            category = interruption_category_from_event(last_event)
        if category is None and state.get("phase") == "failed":
            category = INTERRUPTION_CATEGORY_FAILED
        if category is None:
            return None

        if not raw_cause:
            raw_cause = fallback_cause_from_event(last_event) if last_event else fallback_cause_for_category(category)
        if not raw_resume:
            raw_resume = self._resume_command(feature_dir)
        if raw_log is None and files is not None:
            raw_log = self._log_path(files)

        canonical_event = canonical_interruption_event(last_event) or canonical_event_for_category(category)
        return InterruptionReport(
            category=category,
            cause=raw_cause,
            resume_command=raw_resume,
            log_path=raw_log,
            last_event=canonical_event,
        )

    def build_canceled(self, feature_dir: Path, cause: str, *, files=None) -> InterruptionReport:
        return self._build_report(feature_dir, "canceled", cause, files=files)

    def build_failed(self, feature_dir: Path, cause: str, *, files=None) -> InterruptionReport:
        return self._build_report(feature_dir, "failed", cause, files=files)

    def persist(self, files, report: InterruptionReport) -> None:
        update_phase(
            files.state,
            "failed",
            updated_by="pipeline",
            last_event=report.last_event,
            interruption_category=report.category,
            interruption_cause=report.cause,
            interruption_resume_command=report.resume_command,
            interruption_log_path=report.log_path,
        )

    def render(self, report: InterruptionReport) -> str:
        lines = [
            interruption_title_for_category(report.category),
            f"Cause: {report.cause}",
            f"Resume: {report.resume_command}",
        ]
        if report.log_path:
            lines.append(f"Diagnostics log: {report.log_path}")
        return "\n".join(lines)

    def summarize_subprocess_error(self, exc: subprocess.CalledProcessError) -> str:
        command = exc.cmd if isinstance(exc.cmd, list) else [str(exc.cmd)]
        command_text = " ".join(str(part) for part in command if str(part).strip())
        stderr = self._coalesce_text(exc.stderr or "")
        message = f"Command `{command_text}` failed with exit code {exc.returncode}."
        if stderr:
            message = f"{message} {stderr}"
        return message

    def summarize_exception(self, exc: Exception, *, context: str = "The pipeline crashed unexpectedly.") -> str:
        detail = self._coalesce_text(str(exc))
        if detail:
            return f"{context} {exc.__class__.__name__}: {detail}"
        return f"{context} {exc.__class__.__name__}."

    def _build_report(
        self,
        feature_dir: Path,
        category: InterruptionCategory,
        cause: str,
        *,
        files=None,
    ) -> InterruptionReport:
        normalized_cause = self._coalesce_text(cause) or fallback_cause_for_category(category)
        return InterruptionReport(
            category=category,
            cause=normalized_cause,
            resume_command=self._resume_command(feature_dir),
            log_path=self._log_path(files) if files is not None else None,
            last_event=canonical_event_for_category(category),
        )

    def _resume_command(self, feature_dir: Path) -> str:
        return f"agentmux --resume {shlex.quote(str(feature_dir))}"

    def _log_path(self, files) -> str | None:
        if files.orchestrator_log.exists():
            return str(files.orchestrator_log)
        return None

    def _coalesce_text(self, value: Any) -> str:
        return " ".join(str(value).split()).strip()
