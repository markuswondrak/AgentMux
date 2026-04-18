"""Tests for ValidatingHandler."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agentmux.shared.models import ValidationConfig, WorkflowSettings
from agentmux.workflow.event_catalog import (
    EVENT_IMPLEMENTATION_COMPLETED,
    EVENT_RESUMED,
    EVENT_VALIDATION_FAILED,
    EVENT_VALIDATION_PASSED,
)
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers.validating import ValidatingHandler
from agentmux.workflow.transitions import PipelineContext


def _make_pipeline_context(
    *,
    feature_dir: Path,
    project_dir: Path,
    validation_commands: tuple[str, ...] = (),
) -> PipelineContext:
    implementation_dir = feature_dir / "06_implementation"
    review_dir = feature_dir / "07_review"
    implementation_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    files = MagicMock()
    files.feature_dir = feature_dir
    files.project_dir = project_dir
    files.implementation_dir = implementation_dir
    files.review_dir = review_dir
    files.fix_request = review_dir / "fix_request.md"

    def rel(p: Path) -> str:
        return p.relative_to(feature_dir).as_posix()

    files.relative_path = rel

    runtime = MagicMock()
    ctx = MagicMock(spec=PipelineContext)
    ctx.files = files
    ctx.runtime = runtime
    ctx.workflow_settings = WorkflowSettings(
        validation=ValidationConfig(commands=validation_commands)
    )
    return ctx


class ValidatingHandlerTests(unittest.TestCase):
    def test_empty_commands_skips_pane_fast_paths_to_reviewing(self) -> None:
        handler = ValidatingHandler()
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            project_dir = Path(td)
            ctx = _make_pipeline_context(
                feature_dir=feature_dir, project_dir=project_dir
            )
            state: dict = {}
            result = handler.enter(state, ctx)
            self.assertEqual(result.next_phase, "reviewing")
            ctx.runtime.run_validation_pane.assert_not_called()

    def test_nonempty_commands_dispatches_run_validation_pane(self) -> None:
        handler = ValidatingHandler()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project_dir = root / "proj"
            project_dir.mkdir(parents=True)
            (project_dir / ".agentmux").mkdir(parents=True)
            (project_dir / ".agentmux" / "config.yaml").write_text(
                "version: 2\n", encoding="utf-8"
            )
            feature_dir = project_dir / ".agentmux" / ".sessions" / "feat"
            feature_dir.mkdir(parents=True)
            implementation_dir = feature_dir / "06_implementation"
            implementation_dir.mkdir(parents=True)
            (feature_dir / "07_review").mkdir(parents=True)

            ctx = _make_pipeline_context(
                feature_dir=feature_dir,
                project_dir=project_dir,
                validation_commands=("pytest",),
            )
            state: dict = {"last_event": EVENT_IMPLEMENTATION_COMPLETED}
            handler.enter(state, ctx)

            ctx.runtime.run_validation_pane.assert_called_once()
            call_cmd, label = ctx.runtime.run_validation_pane.call_args[0]
            self.assertEqual(label, "Validating")
            self.assertIn("agentmux.workflow.validation", call_cmd)
            self.assertIn(str(project_dir), call_cmd)

    def test_handle_result_pass_writes_status_and_transitions_reviewing(self) -> None:
        handler = ValidatingHandler()
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            project_dir = Path(td)
            ctx = _make_pipeline_context(
                feature_dir=feature_dir,
                project_dir=project_dir,
                validation_commands=("true",),
            )
            result_file = ctx.files.implementation_dir / "validation_result.json"
            result_file.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "failed_command": "",
                        "exit_code": 0,
                        "tail_output": "",
                        "full_output": "ok\n",
                    }
                ),
                encoding="utf-8",
            )
            event = WorkflowEvent(
                kind="validation_result",
                path="06_implementation/validation_result.json",
            )
            state: dict = {}
            updates, next_phase = handler.handle_event(event, state, ctx)

            self.assertEqual(next_phase, "reviewing")
            self.assertEqual(updates.get("last_event"), EVENT_VALIDATION_PASSED)
            status = ctx.files.review_dir / "validation_status.md"
            self.assertTrue(status.exists())
            self.assertIn("Automated Validation", status.read_text(encoding="utf-8"))

    def test_handle_result_fail_writes_artifacts_and_transitions_fixing(self) -> None:
        handler = ValidatingHandler()
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            project_dir = Path(td)
            ctx = _make_pipeline_context(
                feature_dir=feature_dir,
                project_dir=project_dir,
                validation_commands=("false",),
            )
            result_file = ctx.files.implementation_dir / "validation_result.json"
            result_file.write_text(
                json.dumps(
                    {
                        "passed": False,
                        "failed_command": "ruff check",
                        "exit_code": 1,
                        "tail_output": "E999 error\n",
                        "full_output": "long\n" * 10,
                    }
                ),
                encoding="utf-8",
            )
            event = WorkflowEvent(
                kind="validation_result",
                path="06_implementation/validation_result.json",
            )
            state = {"review_iteration": 0}
            updates, next_phase = handler.handle_event(event, state, ctx)

            self.assertEqual(next_phase, "fixing")
            self.assertEqual(updates.get("last_event"), EVENT_VALIDATION_FAILED)
            self.assertEqual(updates.get("review_iteration"), 1)
            log = ctx.files.review_dir / "validation_failure.log"
            self.assertTrue(log.exists())
            self.assertEqual(log.read_text(encoding="utf-8"), "long\n" * 10)
            fix_req = ctx.files.review_dir / "fix_request.md"
            self.assertTrue(fix_req.exists())
            text = fix_req.read_text(encoding="utf-8")
            self.assertIn("Automated validation failed", text)
            self.assertIn("ruff check", text)

    def test_enter_resumed_with_existing_result_applies_without_pane(self) -> None:
        handler = ValidatingHandler()
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            project_dir = Path(td)
            ctx = _make_pipeline_context(
                feature_dir=feature_dir,
                project_dir=project_dir,
                validation_commands=("pytest",),
            )
            result_file = ctx.files.implementation_dir / "validation_result.json"
            result_file.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "failed_command": "",
                        "exit_code": 0,
                        "tail_output": "",
                        "full_output": "",
                    }
                ),
                encoding="utf-8",
            )
            state = {"last_event": EVENT_RESUMED}
            result = handler.enter(state, ctx)
            self.assertEqual(result.next_phase, "reviewing")
            ctx.runtime.run_validation_pane.assert_not_called()


if __name__ == "__main__":
    unittest.main()
