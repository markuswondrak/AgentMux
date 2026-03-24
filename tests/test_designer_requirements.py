from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import agentmux.pipeline as pipeline
from agentmux.models import AgentConfig
from agentmux.phases import PHASES, get_phase, run_phase_cycle
from agentmux.prompts import build_coder_prompt, build_designer_prompt, build_initial_prompts
from agentmux.state import create_feature_files, load_runtime_files, load_state, write_state
from agentmux.transitions import PipelineContext


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def send(self, role: str, prompt_file: Path) -> None:
        self.calls.append(("send", role, prompt_file.name))

    def send_many(self, role: str, prompt_files: list[Path]) -> None:
        self.calls.append(("send_many", role, [path.name for path in prompt_files]))

    def deactivate(self, role: str) -> None:
        self.calls.append(("deactivate", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


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

    prompts = {"architect": feature_dir / "planning" / "architect_prompt.md"}
    for path in prompts.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    ctx = PipelineContext(
        files=files,
        runtime=FakeRuntime(),
        agents=_base_agents(with_designer=with_designer),
        max_review_iterations=3,
        prompts=prompts,
    )
    return ctx, files.state


class DesignerRequirementsTests(unittest.TestCase):
    def test_load_config_parses_optional_designer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            cfg = {
                "session_name": "s",
                "provider": "claude",
                "architect": {"tier": "max"},
                "coder": {"provider": "codex", "tier": "max"},
                "designer": {
                    "tier": "standard",
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

            self.assertEqual(feature_dir / "design" / "design.md", files.design)
            self.assertEqual(feature_dir / "design" / "design.md", loaded.design)
            self.assertFalse(files.design.exists())

    def test_build_initial_prompts_only_writes_architect_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")

            coder_prompt = build_coder_prompt(files)
            designer_prompt = build_designer_prompt(files)
            initial_prompts = build_initial_prompts(files)

            self.assertIn("done_1", coder_prompt)
            self.assertIn("frontend-design", designer_prompt)
            self.assertIn("design/design.md", designer_prompt)
            self.assertEqual(["architect"], list(initial_prompts.keys()))
            self.assertEqual("architect_prompt.md", initial_prompts["architect"].name)
            self.assertFalse((feature_dir / "implementation" / "coder_prompt.md").exists())
            self.assertFalse((feature_dir / "review" / "review_prompt.md").exists())
            self.assertFalse((feature_dir / "design" / "designer_prompt.md").exists())
            self.assertFalse((feature_dir / "completion" / "confirmation_prompt.md").exists())

    def test_plan_written_moves_to_designing_when_plan_meta_requests_design(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)
            (feature_dir / "planning" / "plan_meta.json").write_text('{"needs_design": true}\n', encoding="utf-8")

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "plan_written", ctx)

            updated = load_state(state_path)
            self.assertEqual("designing", updated["phase"])
            self.assertEqual("plan_written", updated["last_event"])
            self.assertEqual([("deactivate", "architect"), ("kill_primary", "architect")], ctx.runtime.calls)

    def test_enter_designing_builds_designer_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            state = load_state(state_path)
            state["phase"] = "designing"
            write_state(state_path, state)

            run_phase_cycle(load_state(state_path), ctx)

            self.assertEqual([("send", "designer", "designer_prompt.md")], ctx.runtime.calls)
            self.assertTrue((feature_dir / "design" / "designer_prompt.md").exists())

    def test_design_written_hands_off_to_implementing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            state = load_state(state_path)
            state["phase"] = "designing"
            write_state(state_path, state)

            phase = get_phase(load_state(state_path))
            phase.handle_event(load_state(state_path), "design_written", ctx)

            updated = load_state(state_path)
            self.assertEqual("implementing", updated["phase"])
            self.assertEqual("design_written", updated["last_event"])
            self.assertEqual([("deactivate", "designer")], ctx.runtime.calls)

    def test_phase_registry_contains_expected_phases(self) -> None:
        self.assertEqual(
            {
                "product_management",
                "planning",
                "designing",
                "implementing",
                "reviewing",
                "fixing",
                "documenting",
                "completing",
                "failed",
            },
            set(PHASES),
        )


if __name__ == "__main__":
    unittest.main()
