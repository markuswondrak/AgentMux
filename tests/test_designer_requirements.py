from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline
from src.handlers import (
    guard_plan_ready_design,
    handle_design_ready,
    handle_plan_ready_design,
)
from src.models import AgentConfig
from src.prompts import build_coder_prompt, build_designer_prompt, build_initial_prompts
from src.state import create_feature_files, load_runtime_files, load_state, write_state
from src.transitions import PipelineContext


def _base_agents(with_designer: bool = True) -> dict[str, AgentConfig]:
    agents = {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
    }
    if with_designer:
        agents["designer"] = AgentConfig(role="designer", cli="claude", model="sonnet", args=[])
    return agents


def _make_ctx(feature_dir: Path, with_designer: bool = True) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "add designer", "session-x")

    prompts = {
        "architect": feature_dir / "architect_prompt.md",
    }
    for path in prompts.values():
        if not path.exists():
            path.write_text(path.name, encoding="utf-8")

    ctx = PipelineContext(
        files=files,
        panes={"architect": "%1", "coder": None, "docs": None, "designer": None},
        coder_panes={},
        agents=_base_agents(with_designer=with_designer),
        max_review_iterations=3,
        session_name="session-x",
        prompts=prompts,
    )
    return ctx, files.state


class DesignerRequirementsTests(unittest.TestCase):
    def test_load_config_parses_optional_designer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            cfg = {
                "session_name": "s",
                "architect": {"cli": "claude", "model": "opus"},
                "coder": {"cli": "codex", "model": "gpt-5.3-codex"},
                "designer": {
                    "cli": "claude",
                    "model": "sonnet",
                    "args": ["--permission-mode", "acceptEdits"],
                },
            }
            cfg_path = tmp_path / "pipeline_config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            _, agents, _ = pipeline.load_config(cfg_path)

            self.assertIn("designer", agents)
            self.assertEqual("claude", agents["designer"].cli)
            self.assertEqual("sonnet", agents["designer"].model)

    def test_runtime_files_include_design_path_but_no_placeholder_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")
            loaded = load_runtime_files(project_dir, feature_dir)

            self.assertEqual(feature_dir / "design.md", files.design)
            self.assertEqual(feature_dir / "design.md", loaded.design)
            self.assertFalse(files.design.exists())

    def test_build_initial_prompts_only_writes_architect_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")

            coder_prompt = build_coder_prompt(files, state_target="implementation_done")
            designer_prompt = build_designer_prompt(files, state_target="design_ready")
            initial_prompts = build_initial_prompts(files)

            self.assertIn("design.md", coder_prompt)
            self.assertIn("frontend-design", designer_prompt)
            self.assertIn("business logic", designer_prompt)
            self.assertEqual(["architect"], list(initial_prompts.keys()))
            self.assertEqual("architect_prompt.md", initial_prompts["architect"].name)
            self.assertFalse((feature_dir / "coder_prompt.md").exists())
            self.assertFalse((feature_dir / "review_prompt.md").exists())
            self.assertFalse((feature_dir / "designer_prompt.md").exists())
            self.assertFalse((feature_dir / "confirmation_prompt.md").exists())

    def test_guard_plan_ready_design_checks_flag_and_agent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, _ = _make_ctx(feature_dir, with_designer=True)

            state = {"status": "plan_ready", "needs_design": True}
            self.assertTrue(guard_plan_ready_design(state, ctx))

            state = {"status": "plan_ready", "needs_design": False}
            self.assertFalse(guard_plan_ready_design(state, ctx))

            ctx_no_designer, _ = _make_ctx(tmp_path / "feature-2", with_designer=False)
            state = {"status": "plan_ready", "needs_design": True}
            self.assertFalse(guard_plan_ready_design(state, ctx_no_designer))

    def test_handle_plan_ready_design_requests_designer_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            called: dict[str, object] = {}

            def fake_send_prompt(
                target_pane: str | None,
                prompt_file: Path,
                session_name: str | None = None,
                **kwargs: object,
            ) -> None:
                called["send"] = (target_pane, prompt_file.name, session_name, kwargs.get("role"))

            state = load_state(state_path)
            state["status"] = "plan_ready"
            state["needs_design"] = True
            write_state(state_path, state)

            with patch("src.handlers.send_prompt", fake_send_prompt):
                handle_plan_ready_design(load_state(state_path), ctx)

            updated = load_state(state_path)
            self.assertEqual("designer_requested", updated["status"])
            self.assertEqual("designer", updated["active_role"])
            self.assertIsNone(ctx.panes["designer"])
            self.assertEqual((None, "designer_prompt.md", "session-x", "designer"), called["send"])

    def test_handle_design_ready_handoff_back_to_plan_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)
            ctx.panes["designer"] = "%19"
            ctx.handled.add("plan_ready")

            parked: list[tuple[str | None, str]] = []

            def fake_park_agent_pane(pane_id: str | None, session_name: str) -> None:
                parked.append((pane_id, session_name))

            state = load_state(state_path)
            state["status"] = "design_ready"
            state["needs_design"] = True
            write_state(state_path, state)

            with patch("src.handlers.park_agent_pane", fake_park_agent_pane):
                handle_design_ready(load_state(state_path), ctx)

            updated = load_state(state_path)
            self.assertEqual("plan_ready", updated["status"])
            self.assertNotIn("needs_design", updated)
            self.assertEqual("%19", ctx.panes["designer"])
            self.assertIn(("%19", "session-x"), parked)
            self.assertNotIn("plan_ready", ctx.handled)

    def test_plan_ready_designer_transition_precedes_coder_transition(self) -> None:
        plan_ready_transitions = [
            t.description for t in pipeline.TRANSITIONS if t.source == "plan_ready"
        ]
        self.assertTrue(plan_ready_transitions)
        self.assertEqual("plan_ready -> designer_requested", plan_ready_transitions[0])


if __name__ == "__main__":
    unittest.main()
