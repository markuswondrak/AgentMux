from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agentmux import monitor
from agentmux.shared.models import SESSION_DIR_NAMES


class MonitorTests(unittest.TestCase):
    def _render(self, feature_dir: Path, *, width: int = 40, height: int = 24) -> str:
        with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
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

            output = self._strip_ansi(self._render(feature_dir, width=40, height=18))

            self.assertIn(" PIPELINE", output)
            self.assertIn("╭───────────╮", output)
            self.assertIn("│ ▄▀█ █▀▄▀█ │", output)
            self.assertIn("│ █▀█ █ ▀ █ │", output)
            self.assertIn("╰───────────╯", output)
            self.assertIn("monitor soll auch", output)
            self.assertIn("beschreibung des features", output)
            self.assertIn("▶ implementing", output)

    def test_render_falls_back_cleanly_when_monitor_is_narrow(self) -> None:
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

            output = self._strip_ansi(self._render(feature_dir, width=15, height=18))

            self.assertIn("╭───────────╮", output)
            self.assertIn("monitor soll", output)
            self.assertIn("auch…", output)
            self.assertIn("▶ implement", output)

    def test_render_hides_optional_phases_when_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text('{"phase": "reviewing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=50, height=22))

            self.assertIn("✓ planning", output)
            self.assertIn("reviewing", output)
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

            self.assertIn("▶ designing", stripped)
            self.assertLess(stripped.index("✓ planning"), stripped.index("▶ designing"))
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

            self.assertIn("› plan ready", output)
            self.assertNotIn("plan_written", output)

    def test_render_implementing_shows_serial_group_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"implementing","execution_progress":{'
                    '"total_groups":3,'
                    '"completed_groups":1,'
                    '"active_group_index":1,'
                    '"active_group_mode":"serial",'
                    '"active_plan_ids":["plan_2"],'
                    '"groups":[{"id":"g1"},{"id":"g2"},{"id":"g3"}]'
                    "}}"
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› groups: 1/3 done", output)
            self.assertIn("› active: g2 serial · plan_2", output)
            self.assertIn("› done: g1 · queued: g3", output)

    def test_render_implementing_shows_parallel_group_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"implementing","execution_progress":{'
                    '"total_groups":2,'
                    '"completed_groups":0,'
                    '"active_group_index":0,'
                    '"active_group_mode":"parallel",'
                    '"active_plan_ids":["plan_1","plan_2"],'
                    '"groups":[{"id":"g1"},{"id":"g2"}]'
                    "}}"
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› groups: 0/2 done", output)
            self.assertIn("› active: g1 parallel · plan_1, plan_2", output)
            self.assertIn("› queued: g2", output)

    def test_render_implementing_mixed_schedule_summarizes_future_groups(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"implementing","execution_progress":{'
                    '"total_groups":4,'
                    '"completed_groups":1,'
                    '"active_group_index":1,'
                    '"active_group_mode":"parallel",'
                    '"active_plan_ids":["plan_2","plan_3","plan_4"],'
                    '"groups":[{"id":"g1"},{"id":"g2"},{"id":"g3"},{"id":"g4"}]'
                    "}}"
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› groups: 1/4 done", output)
            self.assertIn("› active: g2 parallel · 3 plans", output)
            self.assertIn("› done: g1 · queued: g3, g4", output)

    def test_render_implementing_reads_root_level_implementation_progress_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"implementing",'
                    '"subplan_count":4,'
                    '"implementation_group_total":3,'
                    '"implementation_group_index":2,'
                    '"implementation_group_mode":"parallel",'
                    '"implementation_active_plan_ids":["plan_2","plan_3"],'
                    '"implementation_completed_group_ids":["group_1"]'
                    "}"
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› groups: 1/3 done", output)
            self.assertIn("› active: g2 parallel · plan_2, plan_3", output)
            self.assertIn("› done: g1 · queued: g3", output)
            self.assertNotIn("› 4 subplans", output)

    def test_render_implementing_staged_details_remain_readable_when_narrow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"implementing","execution_progress":{'
                    '"total_groups":3,'
                    '"completed_groups":1,'
                    '"active_group_index":1,'
                    '"active_group_mode":"parallel",'
                    '"active_plan_ids":["plan_2","plan_3"],'
                    '"groups":[{"id":"g1"},{"id":"g2"},{"id":"g3"}]'
                    "}}"
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=34, height=24))

            self.assertIn("› groups:", output)
            self.assertIn("› active:", output)
            self.assertIn("› done:", output)

    def test_render_does_not_show_documents_section_even_when_docs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                '{"phase": "implementing", "last_event": "design_written"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            (feature_dir / "02_planning").mkdir(parents=True, exist_ok=True)
            (feature_dir / "04_design").mkdir(parents=True, exist_ok=True)
            (feature_dir / "02_planning" / "plan.md").write_text("# plan\n", encoding="utf-8")
            (feature_dir / "04_design" / "design.md").write_text("# design\n", encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=15, height=24))

            self.assertNotIn(" DOCUMENTS", output)
            self.assertNotIn("02_planning", output)
            self.assertNotIn("04_design", output)

    def test_render_research_section_uses_numbered_research_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            research_dir = feature_dir / SESSION_DIR_NAMES["research"] / "code-auth-module"

            state_path.write_text(
                '{"phase": "planning", "research_tasks": {"auth-module": "dispatched"}}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            research_dir.mkdir(parents=True, exist_ok=True)
            (research_dir / "done").write_text("", encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=40, height=24))

            self.assertIn(" RESEARCH 1/1", output)
            self.assertIn("✓ c· auth-module", output)

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
                "agentmux.monitor.render_module.get_role_states",
                return_value={"architect": "inactive", "reviewer": "working", "coder": "idle"},
            ):
                with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
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
            self.assertIn("WORKING", output)
            self.assertIn("IDLE", output)

    def test_render_agents_uses_formatted_labels_for_parallel_coders(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            planning_dir = feature_dir / "02_planning"
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "plan_2.md").write_text("## Sub-plan 2: API wiring\n", encoding="utf-8")
            state_path.write_text('{"phase": "implementing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {"coder": "%2"}, "parallel": {"coder": {"2": "%2"}}}', encoding="utf-8")

            agents = {
                "coder": {"cli": "codex", "model": "gpt-5.3-codex"},
            }

            with patch(
                "agentmux.monitor.render_module.get_role_states",
                return_value={"coder_2": "working"},
            ):
                with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
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

            self.assertIn("[coder] API wiring", output)
            self.assertNotIn("coder 2", output)

    def test_render_agents_uses_reviewer_iteration_and_designer_subject(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "tmp"
            feature_dir.mkdir(parents=True, exist_ok=True)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text('{"phase": "reviewing", "review_iteration": 1}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {"reviewer": "%4", "designer": "%5"}}', encoding="utf-8")

            agents = {
                "reviewer": {"cli": "claude", "model": "sonnet"},
                "designer": {"cli": "claude", "model": "sonnet"},
            }

            with patch(
                "agentmux.monitor.render_module.get_role_states",
                return_value={"reviewer": "working", "designer": "idle"},
            ):
                with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                    output = self._strip_ansi(
                        monitor.render(
                            session_name="session-x",
                            state_path=state_path,
                            runtime_state_path=runtime_state_path,
                            agents=agents,
                            width=70,
                            height=24,
                            start_time=0.0,
                        )
                    )

            self.assertIn("[reviewer] iteration 2", output)
            self.assertIn("[designer] tmp", output)

    def test_render_shows_log_section_without_box_frame(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            log_path = feature_dir / "status_log.txt"
            state_path.write_text('{"phase": "planning"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            log_path.write_text(
                "2026-03-21 11:20:05  planning\n2026-03-21 11:20:08  implementing\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        state_path=state_path,
                        runtime_state_path=runtime_state_path,
                        agents={},
                        width=40,
                        height=24,
                        start_time=0.0,
                        log_path=log_path,
                    )
                )

            self.assertIn(" LOG", output)
            self.assertIn("11:20 > planning", output)
            self.assertIn("11:20 > implementing", output)
            self.assertNotIn("╠══ LOG ╣", output)

    def test_render_phase_log_entries_in_white_for_contrast(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            log_path = feature_dir / "status_log.txt"
            state_path.write_text('{"phase": "planning"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            log_path.write_text("2026-03-21 11:20:05  planning\n", encoding="utf-8")

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = monitor.render(
                    session_name="session-x",
                    state_path=state_path,
                    runtime_state_path=runtime_state_path,
                    agents={},
                    width=40,
                    height=24,
                    start_time=0.0,
                    log_path=log_path,
                )

            self.assertIn(f"{monitor.WHITE}> planning{monitor.RESET}", output)

    def test_render_merges_phase_log_with_allowed_created_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            status_log_path = feature_dir / "status_log.txt"
            created_files_log_path = feature_dir / "created_files.log"

            state_path.write_text('{"phase": "planning"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            status_log_path.write_text(
                "2026-03-21 11:20:05  planning\n2026-03-21 11:20:09  implementing\n",
                encoding="utf-8",
            )
            created_files_log_path.write_text(
                "\n".join(
                    [
                        "2026-03-21 11:20:06  context.md",
                        "2026-03-21 11:20:07  02_planning/architect_prompt.md",
                        "2026-03-21 11:20:08  02_planning/plan.md",
                        "2026-03-21 11:20:10  03_research/code-auth/request.md",
                        "2026-03-21 11:20:11  03_research/code-auth/summary.md",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        state_path=state_path,
                        runtime_state_path=runtime_state_path,
                        agents={},
                        width=60,
                        height=30,
                        start_time=0.0,
                        log_path=status_log_path,
                    )
                )

            self.assertIn("11:20 > planning", output)
            self.assertIn("11:20 + 02_planning/plan.md", output)
            self.assertIn("11:20 + 03_research/code-auth/summary.md", output)
            self.assertIn("11:20 > implementing", output)
            self.assertNotIn("context.md", output)
            self.assertNotIn("architect_prompt.md", output)
            self.assertNotIn("code-auth/request.md", output)
            self.assertLess(output.index("11:20 > planning"), output.index("11:20 + 02_planning/plan.md"))
            self.assertLess(output.index("11:20 + 02_planning/plan.md"), output.index("11:20 > implementing"))

    def test_render_shows_allowed_created_file_entries_without_status_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            status_log_path = feature_dir / "status_log.txt"
            created_files_log_path = feature_dir / "created_files.log"

            state_path.write_text('{"phase": "planning"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            created_files_log_path.write_text(
                "2026-03-21 11:20:08  06_review/review.md\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        state_path=state_path,
                        runtime_state_path=runtime_state_path,
                        agents={},
                        width=50,
                        height=24,
                        start_time=0.0,
                        log_path=status_log_path,
                    )
                )

            self.assertIn(" LOG", output)
            self.assertIn("11:20 + 06_review/review.md", output)

    def test_render_failed_state_shows_clean_failure_classification_and_cause(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"failed","last_event":"run_failed",'
                    '"interruption_cause":"Background orchestrator exited unexpectedly."}'
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› run failed unexpectedly", output)
            self.assertIn("› cause: Background orchestrator exited unexpectedly.", output)

    def test_render_legacy_interruption_event_uses_shared_label(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                '{"phase":"failed","last_event":"keyboard_interrupt"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› canceled by user", output)

    def test_get_role_states_treats_dead_tmux_panes_as_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime_state_path = Path(td) / "runtime_state.json"
            runtime_state_path.write_text(
                '{"primary": {"architect": "%1", "reviewer": "%2"}}',
                encoding="utf-8",
            )

            results = [
                CompletedProcess(args=[], returncode=0, stdout="%1 1\n%2 0\n", stderr=""),
                CompletedProcess(args=[], returncode=0, stdout="%1 1\n%2 0\n", stderr=""),
            ]

            with patch("agentmux.monitor.subprocess.run", side_effect=results):
                states = monitor.get_role_states("session-x", runtime_state_path)

            self.assertEqual("inactive", states["architect"])
            self.assertEqual("working", states["reviewer"])


if __name__ == "__main__":
    unittest.main()
