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
            runtime_state_path = feature_dir / "runtime_state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text('{"phase": "implementing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            requirements_path.write_text(
                "# Requirements\n\n## Initial Request\nmonitor soll auch beschreibung des features zeigen\n",
                encoding="utf-8",
            )

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                runtime_state_path=runtime_state_path,
                agents={},
                width=40,
                height=16,
                start_time=0.0,
            )

            self.assertIn("monitor soll auch beschreibung des …", output)

    def test_render_pipeline_shows_all_phases_and_highlights_current(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text('{"phase": "reviewing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                runtime_state_path=runtime_state_path,
                agents={},
                width=50,
                height=22,
                start_time=0.0,
            )

            self.assertIn("· planning", output)
            self.assertIn("▶ reviewing", output)
            self.assertIn("· completing", output)
            self.assertIn("· done", output)

    def test_render_pipeline_shows_last_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                '{"phase": "implementing", "last_event": "plan_written"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = monitor.render(
                session_name="session-x",
                state_path=state_path,
                runtime_state_path=runtime_state_path,
                agents={},
                width=50,
                height=22,
                start_time=0.0,
            )

            self.assertIn("↳ plan_written", output)

    def test_append_status_change_logs_only_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "status_log.txt"

            with patch("src.monitor.time.strftime", side_effect=["2026-03-21 11:20:05", "2026-03-21 11:20:08"]):
                prev = monitor.append_status_change(log_path, prev_status=None, status="planning")
                prev = monitor.append_status_change(log_path, prev_status=prev, status="planning")
                prev = monitor.append_status_change(log_path, prev_status=prev, status="implementing")

            self.assertEqual("implementing", prev)
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                [
                    "2026-03-21 11:20:05  planning",
                    "2026-03-21 11:20:08  implementing",
                ],
                lines,
            )


if __name__ == "__main__":
    unittest.main()
