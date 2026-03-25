from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentmux.pipeline as pipeline
from agentmux import monitor
from agentmux.models import AgentConfig
from agentmux.phases import PHASES, ProductManagementPhase
from agentmux.prompts import build_product_manager_prompt
from agentmux.runtime import TmuxAgentRuntime
from agentmux.state import create_feature_files, infer_resume_phase, load_state, write_state
from agentmux.transitions import PipelineContext


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.primary_panes = {"product-manager": "%7"}

    def send(self, role: str, prompt_file: Path) -> None:
        self.calls.append(("send", role, prompt_file.name))

    def send_many(self, role: str, prompt_files: list[Path]) -> None:
        self.calls.append(("send_many", role, [path.name for path in prompt_files]))

    def spawn_task(self, role: str, task_id: str, prompt_file: Path) -> None:
        self.calls.append(("spawn_task", role, task_id, prompt_file.name))

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

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


class ProductManagerRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(project_dir, feature_dir, "add product manager", "session-x")

        prompts = {"architect": feature_dir / "planning" / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(prompt.name, encoding="utf-8")

        agents = {
            "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
            "product-manager": AgentConfig(role="product-manager", cli="claude", model="opus", args=[]),
            "code-researcher": AgentConfig(role="code-researcher", cli="claude", model="haiku", args=[]),
            "web-researcher": AgentConfig(role="web-researcher", cli="claude", model="sonnet", args=[]),
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
        with patch("sys.argv", ["pipeline.py", "ship feature", "--product-manager"]):
            args = pipeline.parse_args()
        self.assertTrue(args.product_manager)

    def test_load_config_parses_optional_product_manager(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = {
                "session_name": "s",
                "provider": "claude",
                "architect": {"tier": "max"},
                "coder": {"provider": "codex", "tier": "max"},
                "product-manager": {"tier": "max"},
            }
            cfg_path = Path(td) / "pipeline_config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            _, agents, _ = pipeline.load_config(cfg_path)

            self.assertIn("product-manager", agents)
            self.assertEqual("claude", agents["product-manager"].cli)
            self.assertEqual("opus", agents["product-manager"].model)

    def test_create_feature_files_sets_product_management_state_when_flag_enabled(self) -> None:
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

    def test_build_product_manager_prompt_renders_paths_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "pm", "session-x")

            prompt = build_product_manager_prompt(files)

            self.assertIn(str(feature_dir), prompt)
            self.assertIn(str(project_dir), prompt)
            self.assertIn("product_management/analysis.md", prompt)
            self.assertIn("product_management/done", prompt)
            self.assertIn("design/design.md", prompt)

    def test_product_management_phase_entry_and_completion_transition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "product_management"
            write_state(state_path, state)

            phase = ProductManagementPhase()
            phase.on_enter(load_state(state_path), ctx)
            self.assertEqual(("send", "product-manager", "product_manager_prompt.md"), ctx.runtime.calls[-1])

            (feature_dir / "product_management").mkdir(parents=True, exist_ok=True)
            (feature_dir / "product_management" / "done").touch()
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("pm_completed", event)

            phase.handle_event(load_state(state_path), "pm_completed", ctx)
            updated = load_state(state_path)
            self.assertEqual("planning", updated["phase"])
            self.assertEqual("pm_completed", updated["last_event"])
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

            (feature_dir / "research" / "code-market-fit").mkdir(parents=True, exist_ok=True)
            (feature_dir / "research" / "code-market-fit" / "request.md").write_text("analyze", encoding="utf-8")

            phase = ProductManagementPhase()
            self.assertEqual("code_batch_requested", phase.detect_event(load_state(state_path), ctx))

            phase.handle_event(load_state(state_path), "code_batch_requested", ctx)
            self.assertEqual(("spawn_task", "code-researcher", "market-fit", "prompt.md"), ctx.runtime.calls[-1])
            updated = load_state(state_path)
            self.assertEqual("dispatched", updated["research_tasks"]["market-fit"])

            updated["research_tasks"] = {"market-fit": "dispatched"}
            write_state(state_path, updated)
            (feature_dir / "research" / "code-market-fit" / "done").touch()
            with patch("agentmux.phases.send_text") as send_text:
                phase.handle_event(load_state(state_path), "task_completed:market-fit", ctx)

            send_text.assert_called_once_with(
                "%7",
                "Code-research on 'market-fit' is complete. Results are in research/code-market-fit/summary.md and research/code-market-fit/detail.md.",
            )

    def test_infer_resume_phase_handles_product_management_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / "product_management").mkdir(parents=True, exist_ok=True)

            state = {"phase": "planning", "product_manager": True}
            self.assertEqual("product_management", infer_resume_phase(feature_dir, state))

            (feature_dir / "product_management" / "done").touch()
            self.assertEqual("planning", infer_resume_phase(feature_dir, state))

    def test_runtime_create_uses_product_manager_as_initial_pane_when_selected(self) -> None:
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
                config_path: Path,
                trust_snippet: str | None,
                primary_role: str,
            ) -> tuple[dict[str, str | None], object]:
                _ = (session_name, agents_arg, feature_dir_arg, config_path)
                args_seen.append((primary_role, trust_snippet))
                return (
                    {"_control": "%0", "architect": None, "product-manager": "%9"},
                    type("ZoneStub", (), {"visible": []})(),
                )

            with patch("agentmux.runtime.tmux_new_session", side_effect=fake_tmux_new_session):
                TmuxAgentRuntime.create(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=agents,
                    config_path=feature_dir / "pipeline_config.json",
                    initial_role="product-manager",
                )

            self.assertEqual([("product-manager", "pm-trust")], args_seen)

    def test_monitor_pipeline_states_include_product_management(self) -> None:
        self.assertIn("product_management", monitor.PIPELINE_STATES)

    def test_phase_registry_includes_product_management(self) -> None:
        self.assertIn("product_management", PHASES)


if __name__ == "__main__":
    unittest.main()
