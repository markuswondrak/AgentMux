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
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[], trust_snippet=None),
        "docs": AgentConfig(role="docs", cli="codex", model="gpt-5.3-codex", args=[], trust_snippet=None),
    }


class RuntimeTests(unittest.TestCase):
    def test_send_creates_primary_pane_and_persists_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_file = feature_dir / "coder_prompt.md"
            prompt_file.write_text("ship it", encoding="utf-8")
            created: list[tuple[str, str, tuple[str, ...], str | None]] = []

            def fake_create_agent_pane(
                session_name: str,
                role: str,
                agents,
                trust_snippet: str | None,
            ) -> str:
                created.append((session_name, role, tuple(sorted(agents)), trust_snippet))
                return "%42"

            with patch("agentmux.runtime.create_agent_pane", side_effect=fake_create_agent_pane), patch(
                "agentmux.runtime.park_agent_pane", return_value=None
            ), patch("agentmux.runtime.send_prompt", return_value=None):
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1"},
                )
                runtime.send("coder", prompt_file)

            self.assertEqual(
                [("session-x", "coder", ("architect", "coder", "docs"), None)],
                created,
            )
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual("%42", snapshot["primary"]["coder"])

    def test_send_many_tracks_parallel_workers_and_finish_many_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_a = feature_dir / "coder_prompt_1.txt"
            prompt_b = feature_dir / "coder_prompt_2.txt"
            prompt_a.write_text("a", encoding="utf-8")
            prompt_b.write_text("b", encoding="utf-8")
            shown: list[tuple[str, bool]] = []
            sent: list[str] = []
            killed: list[str] = []

            with patch("agentmux.runtime.tmux_pane_exists", side_effect=lambda pane_id: pane_id == "%2"), patch(
                "agentmux.runtime.create_agent_pane", return_value="%99"
            ), patch(
                "agentmux.runtime.show_agent_pane",
                side_effect=lambda pane_id, session_name, exclusive=True: shown.append((pane_id, exclusive)),
            ), patch(
                "agentmux.runtime.send_prompt",
                side_effect=lambda pane_id, prompt_file, *args: sent.append(f"{pane_id}:{prompt_file.name}"),
            ), patch(
                "agentmux.runtime.kill_agent_pane",
                side_effect=lambda pane_id, session_name=None: killed.append(str(pane_id)),
            ):
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1", "coder": "%2"},
                )
                runtime.send_many("coder", [prompt_a, prompt_b])
                runtime.finish_many("coder")

            self.assertEqual([("%2", True), ("%99", False)], shown)
            self.assertEqual(["%2:coder_prompt_1.txt", "%99:coder_prompt_2.txt"], sent)
            self.assertEqual(["%99"], killed)
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual({}, snapshot["parallel"])

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
            ), patch("agentmux.runtime._find_pane_by_title", return_value=None):
                runtime = TmuxAgentRuntime.attach(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                )

            self.assertEqual("%2", runtime.primary_panes["coder"])
            self.assertEqual({1: "%2"}, runtime.parallel_panes["coder"])
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual({"1": "%2"}, snapshot["parallel"]["coder"])

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
            ) -> dict[str, str | None]:
                _ = (session_name, agents, feature_dir_arg, config_path, primary_role)
                args_seen.append(trust_snippet)
                return {"_control": "%0", "architect": "%1", "coder": None, "docs": None}

            with patch("agentmux.runtime.tmux_new_session", side_effect=fake_tmux_new_session):
                TmuxAgentRuntime.create(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    config_path=feature_dir / "pipeline_config.json",
                )

            self.assertEqual(["Do you trust the contents of this directory?"], args_seen)

    def test_kill_primary_kills_pane_clears_registry_and_persists_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with patch("agentmux.runtime.kill_agent_pane") as kill_mock:
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1", "coder": "%2"},
                )
                runtime.kill_primary("architect")

            kill_mock.assert_called_once_with("%1", "session-x")
            self.assertIsNone(runtime.primary_panes["architect"])
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertIsNone(snapshot["primary"]["architect"])


if __name__ == "__main__":
    unittest.main()
