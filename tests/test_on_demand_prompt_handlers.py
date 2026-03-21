from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.handlers import (
    handle_docs_done,
    handle_plan_ready_single,
    handle_start_review,
)
from src.models import AgentConfig
from src.state import create_feature_files, load_state, write_state
from src.transitions import PipelineContext


def _make_ctx(feature_dir: Path, with_docs: bool = True) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "on demand prompt generation", "session-x")
    architect_prompt = feature_dir / "architect_prompt.md"
    architect_prompt.write_text("architect prompt", encoding="utf-8")
    agents = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    panes = {"architect": "%1", "coder": "%2", "docs": "%3", "designer": None}
    if with_docs:
        agents["docs"] = AgentConfig(role="docs", cli="codex", model="gpt-5.3-codex", args=[])
    ctx = PipelineContext(
        files=files,
        panes=panes,
        coder_panes={},
        agents=agents,
        max_review_iterations=3,
        session_name="session-x",
        prompts={"architect": architect_prompt},
    )
    return ctx, files.state


class OnDemandPromptHandlerTests(unittest.TestCase):
    def test_handle_plan_ready_single_builds_coder_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["status"] = "plan_ready"
            write_state(state_path, state)

            sent: dict[str, str] = {}

            def fake_send_prompt(
                target_pane: str | None,
                prompt_file: Path,
                session_name: str | None = None,
                **kwargs: object,
            ) -> None:
                _ = target_pane, session_name, kwargs
                sent["name"] = prompt_file.name

            with patch("src.handlers.send_prompt", fake_send_prompt):
                handle_plan_ready_single(load_state(state_path), ctx)

            self.assertEqual("coder_prompt.md", sent["name"])
            self.assertTrue((ctx.files.feature_dir / "coder_prompt.md").exists())

    def test_handle_start_review_builds_review_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature")
            state = load_state(state_path)
            state["status"] = "implementation_done"
            write_state(state_path, state)

            sent: dict[str, str] = {}

            def fake_send_prompt(
                target_pane: str | None,
                prompt_file: Path,
                session_name: str | None = None,
                **kwargs: object,
            ) -> None:
                _ = target_pane, session_name, kwargs
                sent["name"] = prompt_file.name

            with patch("src.handlers.send_prompt", fake_send_prompt):
                handle_start_review(load_state(state_path), ctx)

            self.assertEqual("review_prompt.md", sent["name"])
            self.assertTrue((ctx.files.feature_dir / "review_prompt.md").exists())

    def test_handle_docs_done_builds_confirmation_prompt_inline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            ctx, state_path = _make_ctx(tmp_path / "feature", with_docs=True)
            state = load_state(state_path)
            state["status"] = "docs_updated"
            write_state(state_path, state)

            sent: dict[str, str] = {}

            def fake_send_prompt(
                target_pane: str | None,
                prompt_file: Path,
                session_name: str | None = None,
                **kwargs: object,
            ) -> None:
                _ = target_pane, session_name, kwargs
                sent["name"] = prompt_file.name

            with patch("src.handlers.send_prompt", fake_send_prompt), patch(
                "src.handlers.park_agent_pane", return_value=None
            ):
                handle_docs_done(load_state(state_path), ctx)

            self.assertEqual("confirmation_prompt.md", sent["name"])
            self.assertTrue((ctx.files.feature_dir / "confirmation_prompt.md").exists())


if __name__ == "__main__":
    unittest.main()
