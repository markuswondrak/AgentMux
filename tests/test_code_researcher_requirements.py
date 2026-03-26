from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.configuration import load_explicit_config
from agentmux.shared.models import AgentConfig, SESSION_DIR_NAMES
from agentmux.workflow.phases import PlanningPhase
from agentmux.workflow.prompts import build_code_researcher_prompt
from agentmux.runtime import TmuxAgentRuntime
from agentmux.sessions.state_store import create_feature_files, load_state, write_state
from agentmux.workflow.transitions import PipelineContext

PLANNING_DIR = SESSION_DIR_NAMES["planning"]
RESEARCH_DIR = SESSION_DIR_NAMES["research"]


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.primary_panes = {"architect": "%1"}

    def send(self, role: str, prompt_file: Path, display_label: str | None = None) -> None:
        self.calls.append(("send", role, prompt_file.name))

    def send_many(self, role: str, prompt_specs: list[object]) -> None:
        self.calls.append(("send_many", role, [Path(getattr(item, "prompt_file", item)).name for item in prompt_specs]))

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

    def notify(self, role: str, text: str) -> None:
        self.calls.append(("notify", role, text))

    def shutdown(self, keep_session: bool) -> None:
        self.calls.append(("shutdown", keep_session))


class FakeZone:
    def __init__(self, session_name: str, visible: list[str] | None = None) -> None:
        self.session_name = session_name
        self.visible = list(visible or [])
        self.restored: list[list[str]] = []
        self.removed: list[str] = []

    def restore(self, known_panes: list[str]) -> None:
        self.restored.append(list(known_panes))

    def remove(self, pane_id: str) -> None:
        self.removed.append(pane_id)
        self.visible = [current for current in self.visible if current != pane_id]

    def show(self, pane_id: str) -> None:
        self.visible = [pane_id]

    def show_parallel(self, pane_ids: list[str]) -> None:
        self.visible = list(pane_ids)

    def hide(self, pane_id: str) -> None:
        self.visible = [current for current in self.visible if current != pane_id]


class CodeResearcherRequirementsTests(unittest.TestCase):
    def _make_ctx(self, feature_dir: Path) -> tuple[PipelineContext, Path]:
        project_dir = feature_dir.parent / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        files = create_feature_files(project_dir, feature_dir, "add code researcher", "session-x")

        prompts = {"architect": feature_dir / PLANNING_DIR / "architect_prompt.md"}
        for prompt in prompts.values():
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(prompt.name, encoding="utf-8")

        agents = {
            "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
            "code-researcher": AgentConfig(role="code-researcher", cli="claude", model="haiku", args=[]),
        }

        ctx = PipelineContext(
            files=files,
            runtime=FakeRuntime(),
            agents=agents,
            max_review_iterations=3,
            prompts=prompts,
        )
        return ctx, files.state

    def test_load_config_parses_optional_code_researcher(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            cfg = {
                "session_name": "s",
                "provider": "claude",
                "architect": {"tier": "max"},
                "coder": {"provider": "codex", "tier": "max"},
                "code-researcher": {
                    "tier": "low",
                    "args": ["--permission-mode", "acceptEdits"],
                },
            }
            cfg_path = tmp_path / "pipeline_config.json"
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

            agents = load_explicit_config(cfg_path).agents

            self.assertIn("code-researcher", agents)
            self.assertEqual("claude", agents["code-researcher"].cli)
            self.assertEqual("haiku", agents["code-researcher"].model)

    def test_build_code_researcher_prompt_renders_topic_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "research", "session-x")

            prompt = build_code_researcher_prompt("auth-module", files)

            self.assertIn(str(feature_dir), prompt)
            self.assertIn(str(project_dir), prompt)
            self.assertIn("03_research/code-auth-module/request.md", prompt)
            self.assertIn("03_research/code-auth-module/done", prompt)

    def test_runtime_supports_string_task_keys_and_spawn_finish_task(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_file = feature_dir / "research_prompt_auth-module.md"
            prompt_file.write_text("research prompt", encoding="utf-8")
            (feature_dir / "runtime_state.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "primary": {"architect": "%1", "coder": "%2", "code-researcher": "%3"},
                        "parallel": {
                            "coder": {"1": "%2"},
                            "code-researcher": {"auth-module": "%9"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            agents = {
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
                "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
                "code-researcher": AgentConfig(role="code-researcher", cli="claude", model="haiku", args=[]),
            }

            sent: list[str] = []

            with patch("agentmux.runtime.tmux_pane_exists", side_effect=lambda pane_id: pane_id in {"%1", "%2", "%3", "%9"}), patch(
                "agentmux.runtime._find_pane_by_title", return_value=None
            ), patch(
                "agentmux.runtime.create_agent_pane", return_value="%77"
            ), patch(
                "agentmux.runtime.ContentZone",
                side_effect=lambda session_name, visible=None: FakeZone(session_name, visible),
            ), patch(
                "agentmux.runtime.send_prompt",
                side_effect=lambda pane_id, pf: sent.append(f"{pane_id}:{pf.name}"),
            ):
                runtime = TmuxAgentRuntime.attach(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=agents,
                )
                self.assertEqual({"auth-module": "%9"}, runtime.parallel_panes["code-researcher"])
                runtime.spawn_task("code-researcher", "db-schema", prompt_file)
                runtime.finish_task("code-researcher", "db-schema")

            self.assertEqual(["%77:research_prompt_auth-module.md"], sent)
            self.assertEqual(["%77"], runtime._zone.removed)
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual({"auth-module": "%9"}, snapshot["parallel"]["code-researcher"])
            self.assertNotIn("db-schema", snapshot["parallel"]["code-researcher"])

    def test_planning_detects_task_requested_and_completed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)

            state = load_state(state_path)
            state["phase"] = "planning"
            state["research_tasks"] = {"auth-module": "dispatched"}
            write_state(state_path, state)

            (feature_dir / RESEARCH_DIR / "code-db-schema").mkdir(parents=True, exist_ok=True)
            (feature_dir / RESEARCH_DIR / "code-auth-module").mkdir(parents=True, exist_ok=True)
            (feature_dir / RESEARCH_DIR / "code-db-schema" / "request.md").write_text("look at db", encoding="utf-8")
            (feature_dir / RESEARCH_DIR / "code-auth-module" / "done").touch()

            phase = PlanningPhase()
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("task_completed:auth-module", event)

            state = load_state(state_path)
            state["research_tasks"] = {}
            write_state(state_path, state)
            (feature_dir / RESEARCH_DIR / "code-auth-module" / "done").unlink()
            event = phase.detect_event(load_state(state_path), ctx)
            self.assertEqual("code_batch_requested", event)

    def test_planning_snapshot_inputs_include_research_request_and_done_markers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            _ = state_path
            (feature_dir / RESEARCH_DIR / "code-auth-module").mkdir(parents=True, exist_ok=True)
            (feature_dir / RESEARCH_DIR / "code-auth-module" / "request.md").write_text("look at auth", encoding="utf-8")
            (feature_dir / RESEARCH_DIR / "code-auth-module" / "done").touch()

            snapshot = PlanningPhase().snapshot_inputs({}, ctx)

            self.assertIn("code-auth-module/request.md", snapshot)
            self.assertIn("code-auth-module/done", snapshot)

    def test_planning_handle_task_requested_spawns_researcher_and_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            state = load_state(state_path)
            state["phase"] = "planning"
            write_state(state_path, state)

            (feature_dir / RESEARCH_DIR / "code-auth-module").mkdir(parents=True, exist_ok=True)
            (feature_dir / RESEARCH_DIR / "code-auth-module" / "request.md").write_text(
                "investigate auth",
                encoding="utf-8",
            )
            stale_done = feature_dir / RESEARCH_DIR / "code-auth-module" / "done"
            stale_done.touch()

            phase = PlanningPhase()
            result = phase.handle_event(load_state(state_path), "code_batch_requested", ctx)

            self.assertIsNone(result)
            self.assertFalse(stale_done.exists())
            self.assertEqual(("spawn_task", "code-researcher", "auth-module", "prompt.md"), ctx.runtime.calls[-1])
            self.assertTrue((feature_dir / RESEARCH_DIR / "code-auth-module" / "prompt.md").exists())
            updated = load_state(state_path)
            self.assertEqual("dispatched", updated["research_tasks"]["auth-module"])

    def test_planning_handle_task_completed_finishes_researcher_and_notifies_architect(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            feature_dir = tmp_path / "feature"
            ctx, state_path = self._make_ctx(feature_dir)
            state = load_state(state_path)
            state["phase"] = "planning"
            state["research_tasks"] = {"auth-module": "dispatched"}
            write_state(state_path, state)
            (feature_dir / RESEARCH_DIR / "code-auth-module").mkdir(parents=True, exist_ok=True)
            (feature_dir / RESEARCH_DIR / "code-auth-module" / "done").touch()

            phase = PlanningPhase()
            result = phase.handle_event(load_state(state_path), "task_completed:auth-module", ctx)

            self.assertIsNone(result)
            self.assertEqual(("notify", "architect",
                "Code-research on 'auth-module' is complete. Read 03_research/code-auth-module/summary.md and continue from there.",
            ), ctx.runtime.calls[-1])
            updated = load_state(state_path)
            self.assertEqual("done", updated["research_tasks"]["auth-module"])


if __name__ == "__main__":
    unittest.main()
