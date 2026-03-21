from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import monitor


class MonitorTests(unittest.TestCase):
    def test_render_shows_feature_description_from_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text('{"status": "coder_requested"}', encoding="utf-8")
            panes_path.write_text("{}", encoding="utf-8")
            requirements_path.write_text(
                "# Requirements\n\n## Initial Request\nmonitor soll auch beschreibung des features zeigen\n",
                encoding="utf-8",
            )

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                panes_path=panes_path,
                agents={},
                width=40,
                height=16,
                start_time=0.0,
            )

            self.assertIn("\n\x1b[1mFeature\x1b[0m\n", output)
            self.assertIn("  \x1b[2mmonitor soll auch beschreibung des …\x1b[0m", output)

    def test_render_pipeline_shows_all_states_and_highlights_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"
            state_path.write_text('{"status": "plan_ready"}', encoding="utf-8")
            panes_path.write_text("{}", encoding="utf-8")

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                panes_path=panes_path,
                agents={},
                width=50,
                height=22,
                start_time=0.0,
            )

            self.assertIn("  \x1b[2marchitect_requested\x1b[0m", output)
            self.assertIn(f"  {monitor.CYAN}\u25ba plan_ready{monitor.RESET}", output)
            self.assertIn("  \x1b[2mcoder_requested\x1b[0m", output)
            self.assertIn("  \x1b[2mcompletion_approved\x1b[0m", output)

    def test_render_pipeline_includes_unknown_status_as_extra_highlighted_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"
            state_path.write_text('{"status": "fix_requested"}', encoding="utf-8")
            panes_path.write_text("{}", encoding="utf-8")

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                panes_path=panes_path,
                agents={},
                width=50,
                height=22,
                start_time=0.0,
            )

            self.assertIn("  \x1b[2mcompletion_approved\x1b[0m", output)
            self.assertIn(f"  {monitor.CYAN}\u25ba fix_requested{monitor.RESET}", output)

    def test_render_does_not_show_log_section_even_if_log_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"
            log_path = feature_dir / "status_log.txt"

            state_path.write_text('{"status": "coder_requested"}', encoding="utf-8")
            panes_path.write_text("{}", encoding="utf-8")
            log_path.write_text("2026-03-21 11:20:00 plan_ready\n", encoding="utf-8")

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                panes_path=panes_path,
                agents={"coder": {"cli": "codex", "model": "gpt-5"}},
                width=40,
                height=25,
                start_time=0.0,
            )

            self.assertIn("\n\x1b[1mAgents\x1b[0m\n", output)
            self.assertNotIn("\n\x1b[1mLog\x1b[0m\n", output)
            self.assertNotIn("11:20 plan_ready", output)

    def test_render_footer_shows_elapsed_duration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"
            state_path.write_text('{"status": "coder_requested", "active_role": "coder"}', encoding="utf-8")
            panes_path.write_text("{}", encoding="utf-8")

            agents = {"coder": {"cli": "codex", "model": "gpt-5"}}

            with patch("src.monitor.get_active_roles", return_value=set()), patch(
                "src.monitor.time.time", return_value=10000.0
            ):
                output = monitor.render(
                    session_name="session-x",
                    state_path=state_path,
                    panes_path=panes_path,
                    agents=agents,
                    width=40,
                    height=30,
                    start_time=6339.0,
                )

            self.assertIn("1:01:01", output)

    def test_render_agents_use_working_active_and_idle_states(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"

            state_path.write_text('{"status": "coder_requested", "active_role": "architect"}', encoding="utf-8")
            panes_path.write_text("{}", encoding="utf-8")

            agents = {
                "architect": {"cli": "codex", "model": "gpt-5"},
                "coder": {"cli": "codex", "model": "gpt-5"},
                "designer": {"cli": "claude", "model": "sonnet"},
            }

            with patch("src.monitor.get_active_roles", return_value={"architect", "coder"}), patch(
                "src.monitor.time.time", return_value=12000.0
            ):
                output = monitor.render(
                    session_name="session-x",
                    state_path=state_path,
                    panes_path=panes_path,
                    agents=agents,
                    width=40,
                    height=30,
                    start_time=11900.0,
                )

            self.assertIn("WORKING", output)
            self.assertIn("ACTIVE", output)
            self.assertIn("IDLE", output)

    def test_append_status_change_logs_only_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "status_log.txt"

            with patch("src.monitor.time.strftime", side_effect=["2026-03-21 11:20:05", "2026-03-21 11:20:08"]):
                prev = monitor.append_status_change(log_path, prev_status=None, status="plan_ready")
                prev = monitor.append_status_change(log_path, prev_status=prev, status="plan_ready")
                prev = monitor.append_status_change(log_path, prev_status=prev, status="coder_requested")

            self.assertEqual("coder_requested", prev)
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [
                    "2026-03-21 11:20:05  plan_ready",
                    "2026-03-21 11:20:08  coder_requested",
                ],
                lines,
            )

    def test_trim_model_strips_cli_prefix_and_limits_to_eight_chars(self) -> None:
        self.assertEqual("opus-4-6", monitor._trim_model("claude-opus-4-6", "claude"))
        self.assertEqual("gpt-5.1-", monitor._trim_model("gpt-5.1-codex-mini", "codex"))
        self.assertEqual("sonnet-4", monitor._trim_model("claude-sonnet-4-6", "claude"))

    def test_render_matches_20_column_design_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            panes_path = feature_dir / "panes.json"

            state_path.write_text(
                '{"status": "architect_requested", "active_role": "architect", "review_iteration": 2, "subplan_count": 3}',
                encoding="utf-8",
            )
            panes_path.write_text("{}", encoding="utf-8")

            agents = {
                "architect": {"cli": "claude", "model": "claude-opus-4-6"},
                "coder": {"cli": "codex", "model": "gpt-5.1-codex-mini"},
                "designer": {"cli": "claude", "model": "claude-sonnet-4-6"},
            }

            with patch("src.monitor.get_active_roles", return_value={"architect", "coder"}), patch(
                "src.monitor.time.time", return_value=10000.0
            ):
                output = monitor.render(
                    session_name="session-x",
                    state_path=state_path,
                    panes_path=panes_path,
                    agents=agents,
                    width=20,
                    height=40,
                    start_time=9738.0,
                )

            self.assertIn("architect_reques", output)
            self.assertIn("review iter 2", output)
            self.assertIn("3 subplans", output)
            self.assertIn("WORKING", output)
            self.assertIn("ACTIVE", output)
            self.assertIn("IDLE", output)
            self.assertIn("claude/opus-4-6", output)
            self.assertIn("codex/gpt-5.1-", output)
            self.assertIn("claude/sonnet-4", output)
            self.assertNotIn("\n\x1b[1mLog\x1b[0m\n", output)
            self.assertIn("↑ 0:04:22", output)


if __name__ == "__main__":
    unittest.main()
