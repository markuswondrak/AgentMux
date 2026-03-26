from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.models import AgentConfig
from agentmux.runtime import TmuxAgentRuntime


def _agents() -> dict[str, AgentConfig]:
    return {
        "architect": AgentConfig(
            role="architect",
            cli="claude",
            model="opus",
            args=[],
            trust_snippet="Do you trust the contents of this directory?",
        ),
        "coder": AgentConfig(
            role="coder",
            cli="codex",
            model="gpt-5.3-codex",
            args=[],
            trust_snippet=None,
        ),
        "docs": AgentConfig(
            role="docs",
            cli="codex",
            model="gpt-5.3-codex",
            args=[],
            trust_snippet=None,
        ),
    }


class FakeZone:
    def __init__(self, session_name: str, visible: list[str] | None = None) -> None:
        self.session_name = session_name
        self.visible = list(visible or [])
        self.shown: list[str] = []
        self.parallel_shows: list[list[str]] = []
        self.hidden: list[str] = []
        self.removed: list[str] = []
        self.restored: list[list[str]] = []

    def show(self, pane_id: str) -> None:
        self.shown.append(pane_id)
        self.visible = [pane_id]

    def show_parallel(self, pane_ids: list[str]) -> None:
        self.parallel_shows.append(list(pane_ids))
        self.visible = list(pane_ids)

    def hide(self, pane_id: str) -> None:
        self.hidden.append(pane_id)
        self.visible = [current for current in self.visible if current != pane_id]

    def hide_all(self) -> None:
        self.visible = []

    def remove(self, pane_id: str) -> None:
        self.removed.append(pane_id)
        self.visible = [current for current in self.visible if current != pane_id]

    def restore(self, known_panes: list[str]) -> None:
        self.restored.append(list(known_panes))
        self.visible = [pane_id for pane_id in self.visible if pane_id in set(known_panes)]


class RuntimeTests(unittest.TestCase):
    def test_send_creates_primary_pane_and_persists_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_file = feature_dir / "coder_prompt.md"
            prompt_file.write_text("ship it", encoding="utf-8")
            created: list[tuple[str, str, tuple[str, ...], str | None]] = []
            zone = FakeZone("session-x")

            def fake_create_agent_pane(
                session_name: str,
                role: str,
                agents,
                trust_snippet: str | None,
            ) -> str:
                created.append((session_name, role, tuple(sorted(agents)), trust_snippet))
                return "%42"

            with patch("agentmux.runtime.create_agent_pane", side_effect=fake_create_agent_pane), patch(
                "agentmux.runtime.send_prompt", return_value=None
            ):
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1"},
                    zone=zone,
                )
                runtime.send("coder", prompt_file)

            self.assertEqual(
                [("session-x", "coder", ("architect", "coder", "docs"), None)],
                created,
            )
            self.assertEqual(["%42"], zone.shown)
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual("%42", snapshot["primary"]["coder"])
            self.assertEqual(["%42"], snapshot["visible"])

    def test_send_many_tracks_parallel_workers_and_finish_many_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_a = feature_dir / "coder_prompt_1.txt"
            prompt_b = feature_dir / "coder_prompt_2.txt"
            prompt_a.write_text("a", encoding="utf-8")
            prompt_b.write_text("b", encoding="utf-8")
            sent: list[str] = []
            zone = FakeZone("session-x")

            with patch("agentmux.runtime.tmux_pane_exists", side_effect=lambda pane_id: pane_id == "%2"), patch(
                "agentmux.runtime.create_agent_pane", return_value="%99"
            ), patch(
                "agentmux.runtime.send_prompt",
                side_effect=lambda pane_id, prompt_file: sent.append(f"{pane_id}:{prompt_file.name}"),
            ):
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1", "coder": "%2"},
                    zone=zone,
                )
                runtime.send_many("coder", [prompt_a, prompt_b])
                runtime.finish_many("coder")

            self.assertEqual([["%2", "%99"]], zone.parallel_shows)
            self.assertEqual(["%2:coder_prompt_1.txt", "%99:coder_prompt_2.txt"], sent)
            self.assertEqual(["%99"], zone.removed)
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual({}, snapshot["parallel"])
            self.assertEqual(["%2"], snapshot["visible"])

    def test_attach_imports_legacy_panes_file_and_discards_stale_parallel_workers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / "panes.json").write_text(
                json.dumps(
                    {
                        "architect": "%1",
                        "coder": "%2",
                        "coder_1": "%2",
                        "coder_2": "%9",
                        "docs": "%3",
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "agentmux.runtime.tmux_pane_exists",
                side_effect=lambda pane_id: pane_id in {"%1", "%2", "%3"},
            ), patch("agentmux.runtime._find_pane_by_title", return_value=None), patch(
                "agentmux.runtime.ContentZone",
                side_effect=lambda session_name, visible=None: FakeZone(session_name, visible),
            ):
                runtime = TmuxAgentRuntime.attach(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                )

            self.assertEqual("%2", runtime.primary_panes["coder"])
            self.assertEqual({1: "%2"}, runtime.parallel_panes["coder"])
            self.assertEqual([["%1", "%2", "%3", "%2"]], runtime._zone.restored)
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual({"1": "%2"}, snapshot["parallel"]["coder"])
            self.assertEqual([], snapshot["visible"])

    def test_create_passes_architect_trust_snippet_to_tmux_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            args_seen: list[str | None] = []

            def fake_tmux_new_session(
                session_name: str,
                agents: dict[str, AgentConfig],
                feature_dir_arg: Path,
                config_path: Path,
                trust_snippet: str | None,
                primary_role: str,
            ) -> tuple[dict[str, str | None], FakeZone]:
                _ = (session_name, agents, feature_dir_arg, config_path, primary_role)
                args_seen.append(trust_snippet)
                return (
                    {"_control": "%0", "architect": "%1", "coder": None, "docs": None},
                    FakeZone("session-x", visible=["%1"]),
                )

            with patch("agentmux.runtime.tmux_new_session", side_effect=fake_tmux_new_session):
                TmuxAgentRuntime.create(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    config_path=feature_dir / "pipeline_config.json",
                )

            self.assertEqual(["Do you trust the contents of this directory?"], args_seen)

    def test_kill_primary_clears_registry_and_persists_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            zone = FakeZone("session-x", visible=["%1"])
            runtime = TmuxAgentRuntime(
                feature_dir=feature_dir,
                session_name="session-x",
                agents=_agents(),
                primary_panes={"architect": "%1", "coder": "%2"},
                zone=zone,
            )
            runtime.kill_primary("architect")

            self.assertEqual(["%1"], zone.removed)
            self.assertIsNone(runtime.primary_panes["architect"])
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertIsNone(snapshot["primary"]["architect"])
            self.assertEqual([], snapshot["visible"])

    def test_registered_and_missing_panes_include_primary_and_parallel_workers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            runtime = TmuxAgentRuntime(
                feature_dir=feature_dir,
                session_name="session-x",
                agents=_agents(),
                primary_panes={"architect": "%1", "coder": "%2"},
                zone=FakeZone("session-x"),
                parallel_panes={"coder": {2: "%9"}},
            )

            with patch("agentmux.runtime.tmux_pane_exists", side_effect=lambda pane_id: pane_id in {"%1", "%2"}):
                registered = runtime.registered_panes()
                missing = runtime.missing_registered_panes()

            self.assertEqual(
                [("architect", "primary", None), ("coder", "primary", None), ("coder", "parallel", 2)],
                [(pane.role, pane.scope, pane.task_id) for pane in registered],
            )
            self.assertEqual([("coder 2", "%9")], [(pane.label, pane.pane_id) for pane in missing])

    def test_send_does_not_recreate_registered_missing_primary_pane(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_file = feature_dir / "coder_prompt.md"
            prompt_file.write_text("ship it", encoding="utf-8")
            zone = FakeZone("session-x")

            with patch("agentmux.runtime.tmux_pane_exists", return_value=False), patch(
                "agentmux.runtime.create_agent_pane"
            ) as create_mock, patch("agentmux.runtime.send_prompt") as send_prompt_mock:
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1", "coder": "%2"},
                    zone=zone,
                )
                runtime.send("coder", prompt_file)

            create_mock.assert_not_called()
            send_prompt_mock.assert_not_called()
            self.assertEqual([], zone.shown)


if __name__ == "__main__":
    unittest.main()
