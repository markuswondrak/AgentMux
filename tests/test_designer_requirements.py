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
from src.prompts import build_all_prompts, build_coder_prompt, build_designer_prompt
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

    designer_prompt = feature_dir / "designer_prompt.md"
    designer_prompt.write_text("designer prompt", encoding="utf-8")

    prompts = {
        "architect": feature_dir / "architect_prompt.md",
        "coder": feature_dir / "coder_prompt.md",
        "review": feature_dir / "review_prompt.md",
        "confirmation": feature_dir / "confirmation_prompt.md",
        "designer": designer_prompt,
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

    def test_runtime_files_include_design_and_placeholder_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")
            loaded = load_runtime_files(project_dir, feature_dir)

            self.assertEqual(feature_dir / "design.md", files.design)
            self.assertEqual(feature_dir / "design.md", loaded.design)
            self.assertTrue(files.design.exists())

    def test_build_prompts_include_designer_and_coder_reads_design(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")

            coder_prompt = build_coder_prompt(files, state_target="implementation_done")
            designer_prompt = build_designer_prompt(files, state_target="design_ready")
            all_prompts = build_all_prompts(files)

            self.assertIn("design.md", coder_prompt)
            self.assertIn("frontend-design", designer_prompt)
            self.assertIn("business logic", designer_prompt)
            self.assertIn("designer", all_prompts)
            self.assertEqual("designer_prompt.md", all_prompts["designer"].name)

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

            def fake_create_agent_pane(session_name: str, agent_name: str, agents: dict[str, AgentConfig]) -> str:
                called["create"] = (session_name, agent_name, sorted(agents))
                return "%9"

            def fake_send_prompt(target_pane: str, prompt_file: Path) -> None:
                called["send"] = (target_pane, prompt_file.name)

            state = load_state(state_path)
            state["status"] = "plan_ready"
            state["needs_design"] = True
            write_state(state_path, state)

            with patch("src.handlers.create_agent_pane", fake_create_agent_pane), patch(
                "src.handlers.send_prompt", fake_send_prompt
            ):
                handle_plan_ready_design(load_state(state_path), ctx)

            updated = load_state(state_path)
            self.assertEqual("designer_requested", updated["status"])
            self.assertEqual("designer", updated["active_role"])
            self.assertEqual("%9", ctx.panes["designer"])
            self.assertEqual("designer", called["create"][1])
            self.assertEqual(("%9", "designer_prompt.md"), called["send"])

    def test_handle_design_ready_handoff_back_to_plan_ready(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)
            ctx.panes["designer"] = "%19"
            ctx.handled.add("plan_ready")

            killed: list[tuple[str | None, str]] = []

            def fake_kill_agent_pane(pane_id: str | None, session_name: str) -> None:
                killed.append((pane_id, session_name))

            state = load_state(state_path)
            state["status"] = "design_ready"
            state["needs_design"] = True
            write_state(state_path, state)

            with patch("src.handlers.kill_agent_pane", fake_kill_agent_pane):
                handle_design_ready(load_state(state_path), ctx)

            updated = load_state(state_path)
            self.assertEqual("plan_ready", updated["status"])
            self.assertNotIn("needs_design", updated)
            self.assertIsNone(ctx.panes["designer"])
            self.assertIn(("%19", "session-x"), killed)
            self.assertNotIn("plan_ready", ctx.handled)

    def test_plan_ready_designer_transition_precedes_coder_transition(self) -> None:
        plan_ready_transitions = [
            t.description for t in pipeline.TRANSITIONS if t.source == "plan_ready"
        ]
        self.assertTrue(plan_ready_transitions)
        self.assertEqual("plan_ready -> designer_requested", plan_ready_transitions[0])


if __name__ == "__main__":
    unittest.main()
