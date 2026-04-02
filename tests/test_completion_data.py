from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.integrations.completion import CompletionResult
from agentmux.sessions.state_store import create_feature_files, load_state
from agentmux.shared.models import GitHubConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PHASE_HANDLERS
from agentmux.workflow.transitions import PipelineContext


class _FakeRuntime:
    pass


def _make_ctx(
    feature_dir: Path, *, branch_prefix: str = "feature/"
) -> tuple[PipelineContext, dict]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(
        project_dir, feature_dir, "persist completion summary", "session-x"
    )
    completion_dir = files.completion_dir
    completion_dir.mkdir(parents=True, exist_ok=True)
    (completion_dir / "approval.json").write_text(
        json.dumps({"action": "approve", "exclude_files": []}),
        encoding="utf-8",
    )
    ctx = PipelineContext(
        files=files,
        runtime=_FakeRuntime(),  # type: ignore[arg-type]
        agents={},
        max_review_iterations=3,
        prompts={},
        github_config=GitHubConfig(branch_prefix=branch_prefix),
    )
    state = load_state(files.state)
    return ctx, state


class CompletionDataPersistenceTests(unittest.TestCase):
    def test_writes_last_completion_json_when_commit_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "20260328-082756-add-welcome-and-goodbye-screen"
            ctx, state = _make_ctx(feature_dir, branch_prefix="work/")

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    return_value="",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.resolve_commit_message",
                    return_value="feat: summary",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
                    return_value=CompletionResult(
                        commit_hash="abc1234",
                        pr_url="https://example.com/pr/123",
                        cleaned_up=True,
                        should_cleanup=True,
                    ),
                ),
            ):
                event = WorkflowEvent(
                    kind="file.created",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = handler.handle_event(event, state, ctx)

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            summary_path = ctx.files.project_dir / ".agentmux" / ".last_completion.json"
            self.assertTrue(summary_path.exists())
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "feature_name": "add-welcome-and-goodbye-screen",
                    "commit_hash": "abc1234",
                    "pr_url": "https://example.com/pr/123",
                    "branch_name": "work/add-welcome-and-goodbye-screen",
                },
                payload,
            )

    def test_skips_last_completion_json_when_no_commit_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "20260328-082756-add-welcome-and-goodbye-screen"
            ctx, state = _make_ctx(feature_dir)

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    return_value="",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.resolve_commit_message",
                    return_value="feat: summary",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
                    return_value=CompletionResult(
                        commit_hash=None,
                        pr_url=None,
                        cleaned_up=False,
                        should_cleanup=False,
                    ),
                ),
            ):
                event = WorkflowEvent(
                    kind="file.created",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = handler.handle_event(event, state, ctx)

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": False}, updates)
            self.assertIsNone(next_phase)
            summary_path = ctx.files.project_dir / ".agentmux" / ".last_completion.json"
            self.assertFalse(summary_path.exists())

    def test_last_completion_json_schema_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "20260328-082756-add-welcome-and-goodbye-screen"
            ctx, state = _make_ctx(feature_dir, branch_prefix="feature/")

            handler = PHASE_HANDLERS.get("completing")
            assert handler is not None

            with (
                patch(
                    "agentmux.workflow.handlers.completing._git_status_porcelain",
                    return_value="",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.resolve_commit_message",
                    return_value="feat: summary",
                ),
                patch(
                    "agentmux.workflow.handlers.completing.COMPLETION_SERVICE.finalize_approval",
                    return_value=CompletionResult(
                        commit_hash="deadbeef",
                        pr_url=None,
                        cleaned_up=True,
                        should_cleanup=True,
                    ),
                ),
            ):
                event = WorkflowEvent(
                    kind="file.created",
                    path="08_completion/approval.json",
                    payload={},
                )
                updates, next_phase = handler.handle_event(event, state, ctx)

            self.assertEqual({"__exit__": 0, "cleanup_feature_dir": True}, updates)
            self.assertIsNone(next_phase)
            summary_path = ctx.files.project_dir / ".agentmux" / ".last_completion.json"
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {"feature_name", "commit_hash", "pr_url", "branch_name"},
                set(payload.keys()),
            )
            self.assertIsInstance(payload["feature_name"], str)
            self.assertIsInstance(payload["commit_hash"], str)
            self.assertIn(type(payload["pr_url"]), (str, type(None)))
            self.assertIsInstance(payload["branch_name"], str)


if __name__ == "__main__":
    unittest.main()
