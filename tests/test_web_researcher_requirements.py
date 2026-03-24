from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agentmux.pipeline as pipeline
from agentmux.models import AgentConfig
from agentmux.phases import PlanningPhase
from agentmux.prompts import build_architect_prompt, build_web_researcher_prompt
from agentmux.state import create_feature_files, load_state, write_state
from agentmux.transitions import PipelineContext


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.primary_panes = {"architect": "%1"}

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

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


class WebResearcherRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(project_dir, feature_dir, "add web researcher", "session-x")

        prompts = {"architect": feature_dir / "planning" / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(prompt.name, encoding="utf-8")

        agents = {
            "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
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

    def test_load_config_parses_optional_web_researcher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            cfg = {
                "session_name": "s",
                "provider": "claude",
                "architect": {"tier": "max"},
                "coder": {"provider": "codex", "tier": "max"},
                "web-researcher": {
                    "tier": "standard",
                    "args": ["--permission-mode", "acceptEdits"],
                },
            }
            cfg_path = tmp_path / "pipeline_config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            _, agents, _ = pipeline.load_config(cfg_path)

            self.assertIn("web-researcher", agents)
            self.assertEqual("claude", agents["web-researcher"].cli)
            self.assertEqual("sonnet", agents["web-researcher"].model)

    def test_build_web_researcher_prompt_renders_topic_and_paths_and_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "research", "session-x")

            prompt = build_web_researcher_prompt("openai-models", files)

            self.assertIn(str(feature_dir), prompt)
            self.assertIn(str(project_dir), prompt)
            self.assertIn("research/web-openai-models/request.md", prompt)
            self.assertIn("research/web-openai-models/done", prompt)
            self.assertIn("version", prompt.lower())
            self.assertTrue(
                "fabricat" in prompt.lower() or "invent" in prompt.lower(),
                "Prompt must explicitly forbid fabricating/inventing facts.",
            )

    def test_architect_prompt_mentions_web_research_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "research", "session-x")

            prompt = build_architect_prompt(files)

            self.assertIn("research/web-<topic>/request.md", prompt)
            self.assertIn("research/web-<topic>/summary.md", prompt)
            self.assertIn("research/web-<topic>/detail.md", prompt)
            self.assertIn("research/web-<topic>/done", prompt)

    def test_planning_detects_web_task_requested_and_completed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "planning"
            state["web_research_tasks"] = {"openai-models": "dispatched"}
            write_state(state_path, state)

            (feature_dir / "research" / "web-react-19").mkdir(parents=True, exist_ok=True)
            (feature_dir / "research" / "web-openai-models").mkdir(parents=True, exist_ok=True)
            (feature_dir / "research" / "web-react-19" / "request.md").write_text("look at react", encoding="utf-8")
            (feature_dir / "research" / "web-openai-models" / "done").touch()

            phase = PlanningPhase()
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("web_task_completed:openai-models", event)

            state = load_state(state_path)
            state["web_research_tasks"] = {}
            write_state(state_path, state)
            (feature_dir / "research" / "web-openai-models" / "done").unlink()
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("web_batch_requested", event)

    def test_planning_snapshot_inputs_include_web_research_request_and_done_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            _ = state_path

            (feature_dir / "research" / "web-openai-models").mkdir(parents=True, exist_ok=True)
            (feature_dir / "research" / "web-openai-models" / "request.md").write_text(
                "look at models",
                encoding="utf-8",
            )
            (feature_dir / "research" / "web-openai-models" / "done").touch()

            snapshot = PlanningPhase().snapshot_inputs({}, ctx)

            self.assertIn("web-openai-models/request.md", snapshot)
            self.assertIn("web-openai-models/done", snapshot)

    def test_planning_handle_web_task_requested_spawns_researcher_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)

            (feature_dir / "research" / "web-openai-models").mkdir(parents=True, exist_ok=True)
            (feature_dir / "research" / "web-openai-models" / "request.md").write_text(
                "investigate models",
                encoding="utf-8",
            )
            stale_done = feature_dir / "research" / "web-openai-models" / "done"
            stale_done.touch()

            phase = PlanningPhase()
            result = phase.handle_event(load_state(state_path), "web_batch_requested", ctx)

            self.assertIsNone(result)
            self.assertFalse(stale_done.exists())
            self.assertEqual(
                ("spawn_task", "web-researcher", "openai-models", "prompt.md"),
                ctx.runtime.calls[-1],
            )
            self.assertTrue((feature_dir / "research" / "web-openai-models" / "prompt.md").exists())
            updated = load_state(state_path)
            self.assertEqual("dispatched", updated["web_research_tasks"]["openai-models"])

    def test_planning_handle_web_task_completed_finishes_researcher_and_notifies_architect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            state = load_state(state_path)
            state["phase"] = "planning"
            state["web_research_tasks"] = {"openai-models": "dispatched"}
            write_state(state_path, state)
            (feature_dir / "research" / "web-openai-models").mkdir(parents=True, exist_ok=True)
            (feature_dir / "research" / "web-openai-models" / "done").touch()

            phase = PlanningPhase()
            with patch("agentmux.phases.send_text") as send_text:
                result = phase.handle_event(load_state(state_path), "web_task_completed:openai-models", ctx)

            self.assertIsNone(result)
            self.assertEqual(("finish_task", "web-researcher", "openai-models"), ctx.runtime.calls[-1])
            send_text.assert_called_once_with(
                "%1",
                "Web research on 'openai-models' is complete. Results are in research/web-openai-models/summary.md and research/web-openai-models/detail.md.",
            )
            updated = load_state(state_path)
            self.assertEqual("done", updated["web_research_tasks"]["openai-models"])


if __name__ == "__main__":
    unittest.main()
