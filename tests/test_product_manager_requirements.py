from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux import monitor
from agentmux.configuration import load_explicit_config
from agentmux.runtime import TmuxAgentRuntime
from agentmux.sessions.state_store import (
    create_feature_files,
    infer_resume_phase,
    load_state,
    write_state,
)
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PHASE_HANDLERS, ProductManagementHandler
from agentmux.workflow.prompts import build_product_manager_prompt
from agentmux.workflow.transitions import PipelineContext

PRODUCT_MANAGEMENT_DIR = SESSION_DIR_NAMES["product_management"]
PLANNING_DIR = SESSION_DIR_NAMES["planning"]
RESEARCH_DIR = SESSION_DIR_NAMES["research"]


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.primary_panes = {"product-manager": "%7"}

    def send(
        self,
        role: str,
        prompt_file: Path,
        display_label: str | None = None,
        prefix_command: str | None = None,
    ) -> None:
        self.calls.append(("send", role, prompt_file.name, prefix_command))

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

    def spawn_task(self, role: str, task_id: str, research_dir: Path) -> None:
        self.calls.append(("spawn_task", role, task_id, research_dir.name))

    def finish_task(self, role: str, task_id: str) -> None:
        self.calls.append(("finish_task", role, task_id))

    def deactivate(self, role: str) -> None:
        self.calls.append(("deactivate", role))

    def deactivate_many(self, roles) -> None:
        self.calls.append(("deactivate_many", tuple(roles)))

    def finish_many(self, role: str) -> None:
        self.calls.append(("finish_many", role))

    def kill_primary(self, role: str) -> None:
        self.calls.append(("kill_primary", role))

    def notify(self, role: str, text: str) -> None:
        self.calls.append(("notify", role, text))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


class ProductManagerRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(
            project_dir, feature_dir, "add product manager", "session-x"
        )

        prompts = {"architect": feature_dir / PLANNING_DIR / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(prompt.name, encoding="utf-8")

        agents = {
            "architect": AgentConfig(
                role="architect", cli="claude", model="opus", args=[]
            ),
            "coder": AgentConfig(
                role="coder", cli="codex", model="gpt-5.3-codex", args=[]
            ),
            "product-manager": AgentConfig(
                role="product-manager", cli="claude", model="opus", args=[]
            ),
            "code-researcher": AgentConfig(
                role="code-researcher", cli="claude", model="haiku", args=[]
            ),
            "web-researcher": AgentConfig(
                role="web-researcher", cli="claude", model="sonnet", args=[]
            ),
        }

        ctx = PipelineContext(
            files=files,
            runtime=FakeRuntime(),
            agents=agents,
            max_review_iterations=3,
            prompts=prompts,
        )
        return ctx, files.state

    def test_parse_args_accepts_product_manager_flag(self) -> None:
        from agentmux.pipeline.cli import build_parser

        with patch(
            "sys.argv", ["agentmux", "run", "ship feature", "--product-manager"]
        ):
            args = build_parser().parse_args()
        self.assertTrue(args.product_manager)

    def test_load_config_parses_optional_product_manager(self) -> None:
        with tempfile.TemporaryDirectory() as td:
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
                    "product-manager": {"model": "opus"},
                },
            }
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            agents = load_explicit_config(cfg_path).agents

            self.assertIn("product-manager", agents)
            self.assertEqual("claude", agents["product-manager"].cli)
            self.assertEqual("opus", agents["product-manager"].model)

    def test_create_feature_files_sets_product_management_state_when_flag_enabled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir,
                feature_dir,
                "pm feature",
                "session-x",
                product_manager=True,
            )

            state = load_state(files.state)
            self.assertEqual("product_management", state["phase"])
            self.assertTrue(state["product_manager"])

    def test_build_product_manager_prompt_renders_paths_and_design_handoff_rules(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "pm", "session-x")

            prompt = build_product_manager_prompt(files)

            self.assertIn(str(feature_dir), prompt)
            self.assertIn(str(project_dir), prompt)
            self.assertIn("01_product_management/analysis.md", prompt)
            self.assertIn("01_product_management/done", prompt)
            self.assertNotIn("04_design/design.md", prompt)
            self.assertNotIn("/frontend-design", prompt)
            self.assertIn("needs_design: true", prompt)
            self.assertIn("must not create design artifacts", prompt)

    def test_product_management_phase_entry_and_completion_transition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)

            handler = ProductManagementHandler()
            handler.enter(load_state(state_path), ctx)
            self.assertEqual(
                ("send", "product-manager", "product_manager_prompt.md", None),
                ctx.runtime.calls[-1],
            )

            (feature_dir / PRODUCT_MANAGEMENT_DIR).mkdir(parents=True, exist_ok=True)
            (feature_dir / PRODUCT_MANAGEMENT_DIR / "done").touch()

            # Create workflow event for done file creation
            event = WorkflowEvent(
                kind="pm_completed",
                path="01_product_management/done",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )
            # Handler returns next_phase as the phase name, not in updates
            self.assertEqual("architecting", next_phase)
            self.assertEqual("pm_completed", updates.get("last_event"))
            self.assertIn(("kill_primary", "product-manager"), ctx.runtime.calls)
            self.assertNotIn(("deactivate", "product-manager"), ctx.runtime.calls)

    def test_product_management_research_dispatch_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            state["research_tasks"] = {}
            write_state(state_path, state)

            (feature_dir / RESEARCH_DIR / "code-market-fit").mkdir(
                parents=True, exist_ok=True
            )
            (feature_dir / RESEARCH_DIR / "code-market-fit" / "request.md").write_text(
                "analyze", encoding="utf-8"
            )

            handler = ProductManagementHandler()
            # Simulate file.created event for research request
            event = WorkflowEvent(
                kind="code_research_requested",
                path="03_research/code-market-fit/request.md",
                payload={},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            # spawn_task now receives the research directory
            self.assertEqual(
                ("spawn_task", "code-researcher", "market-fit", "code-market-fit"),
                ctx.runtime.calls[-1],
            )
            self.assertEqual(
                "dispatched", updates.get("research_tasks", {}).get("market-fit")
            )

            # Simulate research completion - update state with dispatched task
            state = load_state(state_path)
            state["research_tasks"] = {"market-fit": "dispatched"}
            write_state(state_path, state)
            (feature_dir / RESEARCH_DIR / "code-market-fit" / "done").touch()

            done_event = WorkflowEvent(
                kind="code_research_done",
                path="03_research/code-market-fit/done",
                payload={},
            )
            handler.handle_event(done_event, load_state(state_path), ctx)

            self.assertEqual(
                (
                    "notify",
                    "product-manager",
                    "Code-research on 'market-fit' is complete. "
                    "Read 03_research/code-market-fit/summary.md "
                    "and continue from there.",
                ),
                ctx.runtime.calls[-1],
            )

    def test_infer_resume_phase_handles_product_management_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / PRODUCT_MANAGEMENT_DIR).mkdir(parents=True, exist_ok=True)

            state = {"phase": "planning", "product_manager": True}
            self.assertEqual(
                "product_management", infer_resume_phase(feature_dir, state)
            )

            (feature_dir / PRODUCT_MANAGEMENT_DIR / "done").touch()
            self.assertEqual("planning", infer_resume_phase(feature_dir, state))

    def test_runtime_create_uses_product_manager_as_initial_pane_when_selected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            agents = {
                "architect": AgentConfig(
                    role="architect",
                    cli="claude",
                    model="opus",
                    args=[],
                    trust_snippet="architect-trust",
                ),
                "product-manager": AgentConfig(
                    role="product-manager",
                    cli="claude",
                    model="opus",
                    args=[],
                    trust_snippet="pm-trust",
                ),
            }

            args_seen: list[tuple[str, str | None]] = []

            def fake_tmux_new_session(
                session_name: str,
                agents_arg: dict[str, AgentConfig],
                feature_dir_arg: Path,
                project_dir_arg: Path,
                config_path: Path,
                trust_snippet: str | None,
                primary_role: str,
            ) -> tuple[dict[str, str | None], object]:
                _ = (
                    session_name,
                    agents_arg,
                    feature_dir_arg,
                    project_dir_arg,
                    config_path,
                )
                args_seen.append((primary_role, trust_snippet))
                return (
                    {"_control": "%0", "architect": None, "product-manager": "%9"},
                    type("ZoneStub", (), {"visible": []})(),
                )

            with patch(
                "agentmux.runtime.tmux_new_session", side_effect=fake_tmux_new_session
            ):
                TmuxAgentRuntime.create(
                    feature_dir=feature_dir,
                    project_dir=Path("/project"),
                    session_name="session-x",
                    agents=agents,
                    config_path=feature_dir / "config.json",
                    initial_role="product-manager",
                )

            self.assertEqual([("product-manager", "pm-trust")], args_seen)

    def test_monitor_pipeline_states_include_product_management(self) -> None:
        self.assertIn("product_management", monitor.PIPELINE_STATES)

    def test_phase_registry_includes_product_management(self) -> None:
        self.assertIn("product_management", PHASE_HANDLERS)


if __name__ == "__main__":
    unittest.main()
