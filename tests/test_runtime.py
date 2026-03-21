from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.models import AgentConfig
from src.runtime import TmuxAgentRuntime


def _agents() -> dict[str, AgentConfig]:
    return {
        "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
        "coder": AgentConfig(role="coder", cli="codex", model="gpt-5.3-codex", args=[]),
        "docs": AgentConfig(role="docs", cli="codex", model="gpt-5.3-codex", args=[]),
    }


class RuntimeTests(unittest.TestCase):
    def test_send_creates_primary_pane_and_persists_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            prompt_file = feature_dir / "coder_prompt.md"
            prompt_file.write_text("ship it", encoding="utf-8")
            created: list[tuple[str, str, tuple[str, ...]]] = []

            def fake_create_agent_pane(session_name: str, role: str, agents) -> str:
                created.append((session_name, role, tuple(sorted(agents))))
                return "%42"

            with patch("src.runtime.create_agent_pane", side_effect=fake_create_agent_pane), patch(
                "src.runtime.park_agent_pane", return_value=None
            ), patch("src.runtime.send_prompt", return_value=None):
                runtime = TmuxAgentRuntime(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                    primary_panes={"architect": "%1"},
                )
                runtime.send("coder", prompt_file)

            self.assertEqual([("session-x", "coder", ("architect", "coder", "docs"))], created)
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

            with patch("src.runtime.tmux_pane_exists", side_effect=lambda pane_id: pane_id == "%2"), patch(
                "src.runtime.create_agent_pane", return_value="%99"
            ), patch(
                "src.runtime.show_agent_pane",
                side_effect=lambda pane_id, session_name, exclusive=True: shown.append((pane_id, exclusive)),
            ), patch(
                "src.runtime.send_prompt",
                side_effect=lambda pane_id, prompt_file, *args: sent.append(f"{pane_id}:{prompt_file.name}"),
            ), patch(
                "src.runtime.kill_agent_pane",
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
                "src.runtime.tmux_pane_exists",
                side_effect=lambda pane_id: pane_id in {"%1", "%2", "%3"},
            ), patch("src.runtime._find_pane_by_title", return_value=None):
                runtime = TmuxAgentRuntime.attach(
                    feature_dir=feature_dir,
                    session_name="session-x",
                    agents=_agents(),
                )

            self.assertEqual("%2", runtime.primary_panes["coder"])
            self.assertEqual({1: "%2"}, runtime.parallel_panes["coder"])
            snapshot = json.loads((feature_dir / "runtime_state.json").read_text(encoding="utf-8"))
            self.assertEqual({"1": "%2"}, snapshot["parallel"]["coder"])


if __name__ == "__main__":
    unittest.main()
