from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux import monitor


class MonitorTests(unittest.TestCase):
    def _render(self, feature_dir: Path, *, width: int = 40, height: int = 24) -> str:
        return monitor.render(
            session_name="session-x",
            state_path=feature_dir / "state.json",
            runtime_state_path=feature_dir / "runtime_state.json",
            agents={},
            width=width,
            height=height,
            start_time=0.0,
        )

    def _strip_ansi(self, text: str) -> str:
        return monitor._ANSI_RE.sub("", text)

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

            output = self._render(feature_dir, width=40, height=16)

            self.assertIn("monitor soll auch beschreibung des …", output)

    def test_render_hides_optional_phases_when_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text('{"phase": "reviewing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=50, height=22))

            self.assertIn("· planning", output)
            self.assertIn("▶ reviewing", output)
            self.assertIn("· completing", output)
            self.assertIn("· done", output)
            self.assertNotIn("designing", output)
            self.assertNotIn("fixing", output)
            self.assertNotIn("documenting", output)

    def test_render_shows_active_optional_phase_in_cyan_at_natural_position(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                '{"phase": "designing"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._render(feature_dir, width=50, height=22)
            stripped = self._strip_ansi(output)

            self.assertIn(f"{monitor.CYAN}▶ designing", output)
            self.assertLess(stripped.index("· planning"), stripped.index("▶ designing"))
            self.assertLess(stripped.index("▶ designing"), stripped.index("· implementing"))

    def test_render_formats_last_event_label(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                '{"phase": "implementing", "last_event": "plan_written"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=50, height=22))

            self.assertIn("↳ plan ready", output)
            self.assertNotIn("plan_written", output)

    def test_render_adds_empty_rows_around_pipeline_and_documents_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                '{"phase": "implementing", "last_event": "design_written"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            (feature_dir / "planning").mkdir(parents=True, exist_ok=True)
            (feature_dir / "design").mkdir(parents=True, exist_ok=True)
            (feature_dir / "planning" / "plan.md").write_text("# plan\n", encoding="utf-8")
            (feature_dir / "design" / "design.md").write_text("# design\n", encoding="utf-8")

            lines = self._strip_ansi(self._render(feature_dir, width=15, height=24)).splitlines()

            implementing_index = next(i for i, line in enumerate(lines) if "▶ implemen" in line)
            self.assertEqual("║             ║", lines[implementing_index - 3])
            self.assertEqual("║             ║", lines[implementing_index + 4])
            self.assertIn("╠══ DOCUMENTS ╣", lines)
            documents_index = lines.index("╠══ DOCUMENTS ╣")
            self.assertEqual("║             ║", lines[documents_index + 1])
            self.assertTrue(any("planning/" in line for line in lines))
            self.assertTrue(any("design/" in line for line in lines))
            self.assertEqual("║             ║", lines[documents_index + 4])

    def test_append_status_change_logs_only_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            log_path = feature_dir / "status_log.txt"

            with patch("agentmux.monitor.time.strftime", side_effect=["2026-03-21 11:20:05", "2026-03-21 11:20:08"]):
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

    def test_render_agents_hides_inactive_roles_and_shows_active_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text('{"phase": "reviewing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {"architect": "%1", "reviewer": "%2", "coder": "%3"}}', encoding="utf-8")

            agents = {
                "architect": {"cli": "claude", "model": "opus"},
                "reviewer": {"cli": "claude", "model": "sonnet"},
                "coder": {"cli": "codex", "model": "gpt-5.3-codex"},
            }

            with patch(
                "agentmux.monitor.get_role_states",
                return_value={"architect": "inactive", "reviewer": "working", "coder": "idle"},
            ):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        state_path=state_path,
                        runtime_state_path=runtime_state_path,
                        agents=agents,
                        width=60,
                        height=24,
                        start_time=0.0,
                    )
                )

            self.assertNotIn("architect", output)
            self.assertIn("reviewer", output)
            self.assertIn("coder", output)


if __name__ == "__main__":
    unittest.main()
