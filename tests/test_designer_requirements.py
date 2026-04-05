from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentmux.configuration import load_explicit_config
from agentmux.sessions.state_store import (
    create_feature_files,
    load_runtime_files,
    load_state,
    write_state,
)
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PHASE_HANDLERS, DesigningHandler, PlanningHandler
from agentmux.workflow.prompts import (
    build_coder_subplan_prompt,
    build_designer_prompt,
    build_initial_prompts,
)
from agentmux.workflow.transitions import PipelineContext

PLANNING_DIR = SESSION_DIR_NAMES["planning"]
DESIGN_DIR = SESSION_DIR_NAMES["design"]
IMPLEMENTATION_DIR = SESSION_DIR_NAMES["implementation"]
REVIEW_DIR = SESSION_DIR_NAMES["review"]
COMPLETION_DIR = SESSION_DIR_NAMES["completion"]


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def send(
        self,
        role: str,
        prompt_file: Path,
        display_label: str | None = None,
        prefix_command: str | None = None,
    ) -> None:
        self.calls.append(
            ("send", role, prompt_file.name, display_label, prefix_command)
        )

    def send_many(self, role: str, prompt_specs: list[object]) -> None:
        self.calls.append(
            (
                "send_many",
                role,
                [
                    Path(getattr(item, "prompt_file", item)).name
                    for item in prompt_specs
                ],
            )
        )

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
        agents["designer"] = AgentConfig(
            role="designer", cli="claude", model="sonnet", args=[]
        )
    return agents


def _make_ctx(
    feature_dir: Path, with_designer: bool = True
) -> tuple[PipelineContext, Path]:
    project_dir = feature_dir.parent / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    files = create_feature_files(project_dir, feature_dir, "add designer", "session-x")
    files.plan.parent.mkdir(parents=True, exist_ok=True)
    files.plan.write_text("# Plan\n", encoding="utf-8")

    prompts = {"architect": feature_dir / PLANNING_DIR / "architect_prompt.md"}
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


def _write_execution_plan(feature_dir: Path, *, name: str = "implementation") -> None:
    planning_dir = feature_dir / PLANNING_DIR
    planning_dir.mkdir(parents=True, exist_ok=True)
    (planning_dir / "plan_1.md").write_text(
        f"## Sub-plan 1: {name}\n", encoding="utf-8"
    )
    (planning_dir / "tasks_1.md").write_text(
        "# Tasks for plan 1\n\n- [ ] task\n", encoding="utf-8"
    )
    (planning_dir / "execution_plan.json").write_text(
        json.dumps(
            {
                "version": 1,
                "groups": [
                    {
                        "group_id": "g1",
                        "mode": "serial",
                        "plans": [{"file": "plan_1.md", "name": name}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class DesignerRequirementsTests(unittest.TestCase):
    def _write_coder_inputs(self, feature_dir: Path) -> None:
        planning_dir = feature_dir / PLANNING_DIR
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / "plan_1.md").write_text(
            "## Sub-plan 1: implementation\n", encoding="utf-8"
        )
        (planning_dir / "tasks_1.md").write_text(
            "# Tasks for plan 1\n\n- [ ] one task\n", encoding="utf-8"
        )

    def test_load_config_parses_optional_designer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            cfg = {
                "version": 2,
                "defaults": {
                    "session_name": "s",
                    "provider": "claude",
                    "model": "sonnet",
                },
                "roles": {
                    "architect": {"model": "opus"},
                    "coder": {"provider": "codex", "model": "gpt-5.4"},
                    "designer": {
                        "model": "sonnet",
                        "args": ["--permission-mode", "acceptEdits"],
                    },
                },
            }
            cfg_path = tmp_path / "config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            agents = load_explicit_config(cfg_path).agents

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

            self.assertEqual(feature_dir / DESIGN_DIR / "design.md", files.design)
            self.assertEqual(feature_dir / DESIGN_DIR / "design.md", loaded.design)
            self.assertFalse(files.design.exists())

    def test_build_initial_prompts_only_writes_architect_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")
            files.plan.parent.mkdir(parents=True, exist_ok=True)
            files.plan.write_text("# Plan\n", encoding="utf-8")
            self._write_coder_inputs(feature_dir)

            coder_prompt = build_coder_subplan_prompt(
                files, feature_dir / PLANNING_DIR / "plan_1.md", 1
            )
            designer_prompt = build_designer_prompt(files)
            initial_prompts = build_initial_prompts(files)

            self.assertIn("done_1", coder_prompt)
            self.assertIn("frontend-design", designer_prompt)
            self.assertIn("04_design/design.md", designer_prompt)
            self.assertNotIn("[[placeholder:", coder_prompt)
            self.assertNotIn("[[placeholder:", designer_prompt)
            self.assertEqual({}, initial_prompts)
            self.assertFalse(
                (feature_dir / IMPLEMENTATION_DIR / "coder_prompt.md").exists()
            )
            self.assertFalse((feature_dir / REVIEW_DIR / "review_prompt.md").exists())
            self.assertFalse((feature_dir / DESIGN_DIR / "designer_prompt.md").exists())
            self.assertFalse(
                (feature_dir / COMPLETION_DIR / "confirmation_prompt.md").exists()
            )

    def test_build_designer_prompt_includes_design_contract_additions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "do ui", "session")
            files.plan.parent.mkdir(parents=True, exist_ok=True)
            files.plan.write_text("# Plan\n", encoding="utf-8")
            designer_prompt = build_designer_prompt(files)

            self.assertIn("tailwind.config.js", designer_prompt)
            self.assertIn("theme.ts", designer_prompt)
            self.assertIn("Integration Instructions", designer_prompt)
            self.assertIn("classes", designer_prompt)
            self.assertIn("CSS import", designer_prompt)
            self.assertIn("Initial-State", designer_prompt)
            self.assertIn("Loading-State", designer_prompt)
            self.assertIn("Error-State", designer_prompt)

    def test_plan_written_moves_to_designing_when_plan_meta_requests_design(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)
            _write_execution_plan(feature_dir, name="implementation")
            (feature_dir / PLANNING_DIR).mkdir(parents=True, exist_ok=True)
            # Write all three required files for plan completion
            (feature_dir / PLANNING_DIR / "plan.md").write_text(
                "# Plan\n", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "tasks.md").write_text(
                "# Tasks\n\n- [ ] task\n", encoding="utf-8"
            )
            (feature_dir / PLANNING_DIR / "plan_meta.json").write_text(
                '{"needs_design": true}\n', encoding="utf-8"
            )

            handler = PlanningHandler()
            event = WorkflowEvent(
                kind="plan_written",
                path="02_planning/plan_meta.json",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("designing", next_phase)
            self.assertEqual("plan_written", updates.get("last_event"))
            self.assertIn(("deactivate", "planner"), ctx.runtime.calls)
            self.assertIn(("kill_primary", "planner"), ctx.runtime.calls)

    def test_enter_designing_builds_designer_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            state = load_state(state_path)
            state["phase"] = "designing"
            write_state(state_path, state)

            handler = DesigningHandler()
            handler.enter(load_state(state_path), ctx)

            self.assertEqual(
                [
                    (
                        "send",
                        "designer",
                        "designer_prompt.md",
                        "[designer] feature",
                        None,
                    )
                ],
                ctx.runtime.calls,
            )
            self.assertTrue((feature_dir / DESIGN_DIR / "designer_prompt.md").exists())

    def test_design_written_hands_off_to_implementing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = _make_ctx(feature_dir, with_designer=True)

            state = load_state(state_path)
            state["phase"] = "designing"
            write_state(state_path, state)

            handler = DesigningHandler()
            event = WorkflowEvent(
                kind="design_written",
                path="04_design/design.md",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertEqual("implementing", next_phase)
            self.assertEqual("design_written", updates.get("last_event"))
            self.assertIn(("deactivate", "designer"), ctx.runtime.calls)

    def test_phase_registry_contains_expected_phases(self) -> None:
        self.assertEqual(
            {
                "product_management",
                "architecting",
                "planning",
                "designing",
                "implementing",
                "reviewing",
                "fixing",
                "completing",
                "failed",
            },
            set(PHASE_HANDLERS),
        )


if __name__ == "__main__":
    unittest.main()
