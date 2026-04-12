from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentmux.configuration import load_explicit_config
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig
from agentmux.workflow.event_router import WorkflowEvent
from agentmux.workflow.handlers import PlanningHandler
from agentmux.workflow.prompts import (
    build_architect_prompt,
    build_web_researcher_prompt,
)
from agentmux.workflow.transitions import PipelineContext

PLANNING_DIR = SESSION_DIR_NAMES["planning"]
RESEARCH_DIR = SESSION_DIR_NAMES["research"]


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.primary_panes = {"architect": "%1"}

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

    def notify(self, role: str, text: str) -> None:
        self.calls.append(("notify", role, text))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


class WebResearcherRequirementsTests(unittest.TestCase):
    def _write_web_request(self, feature_dir: Path, topic: str) -> None:
        request_path = feature_dir / RESEARCH_DIR / f"web-{topic}" / "request.md"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text("research request\n", encoding="utf-8")

    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(
            project_dir, feature_dir, "add web researcher", "session-x"
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

    def test_load_config_parses_optional_web_researcher(self) -> None:
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
                    "web-researcher": {
                        "model": "sonnet",
                        "args": ["--permission-mode", "acceptEdits"],
                    },
                },
            }
            cfg_path = tmp_path / "config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            agents = load_explicit_config(cfg_path).agents

            self.assertIn("web-researcher", agents)
            self.assertEqual("claude", agents["web-researcher"].cli)
            self.assertEqual("sonnet", agents["web-researcher"].model)

    def test_build_web_researcher_prompt_renders_topic_and_paths_and_constraints(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(
                project_dir, feature_dir, "research", "session-x"
            )
            self._write_web_request(feature_dir, "openai-models")

            prompt = build_web_researcher_prompt("openai-models", files)

            self.assertIn(str(feature_dir), prompt)
            self.assertIn(str(project_dir), prompt)
            self.assertIn("03_research/web-openai-models/request.md", prompt)
            self.assertIn("03_research/web-openai-models/done", prompt)
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
            files = create_feature_files(
                project_dir, feature_dir, "research", "session-x"
            )

            prompt = build_architect_prompt(files)

            self.assertIn("03_research/web-<topic>/summary.md", prompt)
            self.assertIn("03_research/web-<topic>/detail.md", prompt)
            self.assertIn("research_dispatch_web", prompt)

    def test_planning_handle_web_task_requested_spawns_researcher_and_updates_state(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)

            handler = PlanningHandler()
            event = WorkflowEvent(
                kind="research_web_req",
                payload={
                    "payload": {
                        "topic": "openai-models",
                        "context": "Investigate OpenAI models API",
                        "questions": ["What models are available?"],
                        "scope_hints": [],
                    }
                },
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertIsNone(next_phase)
            # spawn_task receives the research directory
            self.assertEqual(
                ("spawn_task", "web-researcher", "openai-models", "web-openai-models"),
                ctx.runtime.calls[-1],
            )
            research_dir = feature_dir / RESEARCH_DIR / "web-openai-models"
            self.assertTrue((research_dir / "request.md").exists())
            self.assertEqual(
                "dispatched", updates.get("web_research_tasks", {}).get("openai-models")
            )

    def test_planning_handle_web_task_completed_finishes_researcher(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            state = load_state(state_path)
            state["phase"] = "planning"
            state["web_research_tasks"] = {"openai-models": "dispatched"}
            write_state(state_path, state)
            handler = PlanningHandler()
            event = WorkflowEvent(
                kind="research_done",
                payload={"payload": {"topic": "openai-models", "role_type": "web"}},
            )
            updates, next_phase = handler.handle_event(
                event, load_state(state_path), ctx
            )

            self.assertIsNone(next_phase)
            self.assertEqual(
                (
                    "notify",
                    "planner",
                    "Web research on 'openai-models' is complete. "
                    "Read 03_research/web-openai-models/summary.md "
                    "and continue from there.",
                ),
                ctx.runtime.calls[-1],
            )
            self.assertEqual(
                "done", updates.get("web_research_tasks", {}).get("openai-models")
            )


if __name__ == "__main__":
    unittest.main()
