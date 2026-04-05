from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from agentmux import monitor
from agentmux.agent_labels import role_display_label
from agentmux.monitor.state_reader import (
    EVENT_LABELS,
    OPTIONAL_PHASES,
    PIPELINE_STATES,
    read_session_summary,
)
from agentmux.shared.models import SESSION_DIR_NAMES, RuntimeFiles


def _make_test_files(feature_dir: Path) -> RuntimeFiles:
    """Create a minimal RuntimeFiles for testing."""
    return RuntimeFiles(
        project_dir=feature_dir.parent,
        feature_dir=feature_dir,
        product_management_dir=feature_dir / SESSION_DIR_NAMES["product_management"],
        planning_dir=feature_dir / SESSION_DIR_NAMES["planning"],
        research_dir=feature_dir / SESSION_DIR_NAMES["research"],
        design_dir=feature_dir / SESSION_DIR_NAMES["design"],
        implementation_dir=feature_dir / SESSION_DIR_NAMES["implementation"],
        review_dir=feature_dir / SESSION_DIR_NAMES["review"],
        completion_dir=feature_dir / SESSION_DIR_NAMES["completion"],
        context=feature_dir / "context.md",
        requirements=feature_dir / "requirements.md",
        plan=feature_dir / SESSION_DIR_NAMES["planning"] / "plan.md",
        architecture=feature_dir / SESSION_DIR_NAMES["planning"] / "architecture.md",
        tasks=feature_dir / SESSION_DIR_NAMES["planning"] / "tasks.md",
        execution_plan=feature_dir
        / SESSION_DIR_NAMES["planning"]
        / "execution_plan.json",
        design=feature_dir / SESSION_DIR_NAMES["design"] / "design.md",
        review=feature_dir / SESSION_DIR_NAMES["review"] / "review.md",
        fix_request=feature_dir / SESSION_DIR_NAMES["review"] / "fix_request.md",
        changes=feature_dir / SESSION_DIR_NAMES["completion"] / "changes.md",
        summary=feature_dir / SESSION_DIR_NAMES["completion"] / "summary.md",
        pm_preference_proposal=feature_dir
        / SESSION_DIR_NAMES["product_management"]
        / "approved_preferences.json",
        architect_preference_proposal=feature_dir
        / SESSION_DIR_NAMES["planning"]
        / "approved_preferences.json",
        reviewer_preference_proposal=feature_dir
        / SESSION_DIR_NAMES["completion"]
        / "approved_preferences.json",
        state=feature_dir / "state.json",
        runtime_state=feature_dir / "runtime_state.json",
        orchestrator_log=feature_dir / "orchestrator.log",
        created_files_log=feature_dir / "created_files.log",
        status_log=feature_dir / "status_log.txt",
    )


class MonitorTests(unittest.TestCase):
    def _render(self, feature_dir: Path, *, width: int = 40, height: int = 24) -> str:
        files = _make_test_files(feature_dir)
        with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
            return monitor.render(
                session_name="session-x",
                files=files,
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
                (
                    "# Requirements\n\n## Initial Request\n"
                    "monitor soll auch beschreibung des features zeigen\n"
                ),
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

    def test_state_reader_no_longer_lists_removed_docs_phase_or_event_markers(
        self,
    ) -> None:
        self.assertNotIn("documenting", OPTIONAL_PHASES)
        self.assertNotIn("documenting", PIPELINE_STATES)
        self.assertNotIn("docs_written", EVENT_LABELS)

    def test_render_falls_back_cleanly_when_monitor_is_narrow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text('{"phase": "implementing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            requirements_path.write_text(
                (
                    "# Requirements\n\n## Initial Request\n"
                    "monitor soll auch beschreibung des features zeigen\n"
                ),
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

    def test_render_shows_active_optional_phase_in_cyan_at_natural_position(
        self,
    ) -> None:
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
            self.assertLess(
                stripped.index("▶ designing"), stripped.index("· implementing")
            )

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

    def test_render_implementing_reads_root_level_implementation_progress_fields(
        self,
    ) -> None:
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

    def test_render_implementing_staged_details_remain_readable_when_narrow(
        self,
    ) -> None:
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
            (feature_dir / "02_planning" / "plan.md").write_text(
                "# plan\n", encoding="utf-8"
            )
            (feature_dir / "04_design" / "design.md").write_text(
                "# design\n", encoding="utf-8"
            )

            output = self._strip_ansi(self._render(feature_dir, width=15, height=24))

            self.assertNotIn(" DOCUMENTS", output)
            self.assertNotIn("02_planning", output)
            self.assertNotIn("04_design", output)

    def test_render_research_section_uses_numbered_research_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            research_dir = (
                feature_dir / SESSION_DIR_NAMES["research"] / "code-auth-module"
            )

            state_path.write_text(
                (
                    '{"phase": "planning", "research_tasks": '
                    '{"auth-module": "dispatched"}}'
                ),
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

            with patch(
                "agentmux.monitor.time.strftime",
                side_effect=["2026-03-21 11:20:05", "2026-03-21 11:20:08"],
            ):
                prev = monitor.append_status_change(
                    log_path, prev_status=None, status="planning"
                )
                prev = monitor.append_status_change(
                    log_path, prev_status=prev, status="planning"
                )
                prev = monitor.append_status_change(
                    log_path, prev_status=prev, status="implementing"
                )

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
            files = _make_test_files(feature_dir)
            files.state.write_text('{"phase": "reviewing"}', encoding="utf-8")
            files.runtime_state.write_text(
                '{"primary": {"architect": "%1", "reviewer": "%2", "coder": "%3"}}',
                encoding="utf-8",
            )

            agents = {
                "architect": {"cli": "claude", "model": "opus"},
                "reviewer": {"cli": "claude", "model": "sonnet"},
                "coder": {"cli": "codex", "model": "gpt-5.3-codex"},
            }

            with (
                patch(
                    "agentmux.monitor.render_module.get_role_states",
                    return_value={
                        "architect": "inactive",
                        "reviewer": "working",
                        "coder": "idle",
                    },
                ),
                patch("agentmux.monitor.render_module.time.time", return_value=0.0),
            ):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        files=files,
                        agents=agents,
                        width=60,
                        height=24,
                        start_time=0.0,
                    )
                )

            self.assertNotIn("● architect", output)
            self.assertNotIn("[architect]", output)
            self.assertIn("reviewer", output)
            self.assertIn("coder", output)
            self.assertIn("WORKING", output)
            self.assertIn("IDLE", output)

    def test_render_agents_uses_formatted_labels_for_parallel_coders(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)
            planning_dir = files.planning_dir
            planning_dir.mkdir(parents=True, exist_ok=True)
            (planning_dir / "plan_2.md").write_text(
                "## Sub-plan 2: API wiring\n", encoding="utf-8"
            )
            (planning_dir / "execution_plan.json").write_text(
                (
                    '{"version": 1, "groups": [{"group_id": "g1", "mode": "parallel", '
                    '"plans": [{"file": "plan_2.md", "name": "API wiring"}]}]}'
                ),
                encoding="utf-8",
            )
            files.state.write_text('{"phase": "implementing"}', encoding="utf-8")
            files.runtime_state.write_text(
                '{"primary": {"coder": "%2"}, "parallel": {"coder": {"2": "%2"}}}',
                encoding="utf-8",
            )

            agents = {
                "coder": {"cli": "codex", "model": "gpt-5.3-codex"},
            }

            with (
                patch(
                    "agentmux.monitor.render_module.get_role_states",
                    return_value={"coder_2": "working"},
                ),
                patch("agentmux.monitor.render_module.time.time", return_value=0.0),
            ):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        files=files,
                        agents=agents,
                        width=60,
                        height=24,
                        start_time=0.0,
                    )
                )

            self.assertIn("[coder] API wiring", output)
            self.assertNotIn("coder 2", output)

    def test_render_agents_uses_reviewer_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "tmp"
            feature_dir.mkdir(parents=True, exist_ok=True)
            files = _make_test_files(feature_dir)
            files.state.write_text(
                '{"phase": "reviewing", "review_iteration": 1}', encoding="utf-8"
            )
            files.runtime_state.write_text(
                '{"primary": {"reviewer": "%4"}}', encoding="utf-8"
            )

            agents = {
                "reviewer": {"cli": "claude", "model": "sonnet"},
            }

            with (
                patch(
                    "agentmux.monitor.render_module.get_role_states",
                    return_value={"reviewer": "working"},
                ),
                patch("agentmux.monitor.render_module.time.time", return_value=0.0),
            ):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        files=files,
                        agents=agents,
                        width=70,
                        height=24,
                        start_time=0.0,
                    )
                )

            self.assertIn("[reviewer] iteration 2", output)

    def test_render_shows_log_section_without_box_frame(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)
            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.status_log.write_text(
                "2026-03-21 11:20:05  planning\n2026-03-21 11:20:08  implementing\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        files=files,
                        agents={},
                        width=40,
                        height=24,
                        start_time=0.0,
                        log_path=files.status_log,
                    )
                )

            self.assertIn(" LOG", output)
            self.assertIn("11:20 > planning", output)
            self.assertIn("11:20 > implementing", output)
            self.assertNotIn("╠══ LOG ╣", output)

    def test_render_phase_log_entries_in_white_for_contrast(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)
            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.status_log.write_text(
                "2026-03-21 11:20:05  planning\n", encoding="utf-8"
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = monitor.render(
                    session_name="session-x",
                    files=files,
                    agents={},
                    width=40,
                    height=24,
                    start_time=0.0,
                    log_path=files.status_log,
                )

            self.assertIn(f"{monitor.WHITE}> planning{monitor.RESET}", output)

    def test_render_merges_phase_log_with_allowed_created_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)

            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.status_log.write_text(
                "2026-03-21 11:20:05  planning\n2026-03-21 11:20:09  implementing\n",
                encoding="utf-8",
            )
            files.created_files_log.write_text(
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
                        files=files,
                        agents={},
                        width=60,
                        height=30,
                        start_time=0.0,
                        log_path=files.status_log,
                    )
                )

            self.assertIn("11:20 > planning", output)
            self.assertIn("11:20 + 02_planning/plan.md", output)
            self.assertIn("11:20 + 03_research/code-auth/summary.md", output)
            self.assertIn("11:20 > implementing", output)
            self.assertNotIn("context.md", output)
            self.assertNotIn("architect_prompt.md", output)
            self.assertNotIn("code-auth/request.md", output)
            self.assertLess(
                output.index("11:20 > planning"),
                output.index("11:20 + 02_planning/plan.md"),
            )
            self.assertLess(
                output.index("11:20 + 02_planning/plan.md"),
                output.index("11:20 > implementing"),
            )

    def test_render_shows_allowed_created_file_entries_without_status_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)

            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.created_files_log.write_text(
                "2026-03-21 11:20:08  06_review/review.md\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = self._strip_ansi(
                    monitor.render(
                        session_name="session-x",
                        files=files,
                        agents={},
                        width=50,
                        height=24,
                        start_time=0.0,
                        log_path=files.status_log,
                    )
                )

            self.assertIn(" LOG", output)
            self.assertIn("11:20 + 06_review/review.md", output)

    def test_render_failed_state_shows_clean_failure_classification_and_cause(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            state_path.write_text(
                (
                    '{"phase":"failed","last_event":"run_failed",'
                    '"interruption_cause":"Background orchestrator exited."}'
                ),
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=80, height=24))

            self.assertIn("› run failed unexpectedly", output)
            self.assertIn("› cause: Background orchestrator exited.", output)

    def test_render_unknown_interruption_event_falls_back_to_raw_label(self) -> None:
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

            self.assertIn("› keyboard interrupt", output)

    def test_get_role_states_treats_dead_tmux_panes_as_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime_state_path = Path(td) / "runtime_state.json"
            runtime_state_path.write_text(
                '{"primary": {"architect": "%1", "reviewer": "%2"}}',
                encoding="utf-8",
            )

            results = [
                CompletedProcess(
                    args=[], returncode=0, stdout="%1 1\n%2 0\n", stderr=""
                ),
                CompletedProcess(
                    args=[], returncode=0, stdout="%1 1\n%2 0\n", stderr=""
                ),
            ]

            with patch("agentmux.monitor.subprocess.run", side_effect=results):
                states = monitor.get_role_states("session-x", runtime_state_path)

            self.assertEqual("inactive", states["architect"])
            self.assertEqual("working", states["reviewer"])

    def test_render_file_log_entries_contain_osc8_hyperlinks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)

            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.created_files_log.write_text(
                "2026-03-21 11:20:08  02_planning/plan.md\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = monitor.render(
                    session_name="session-x",
                    files=files,
                    agents={},
                    width=60,
                    height=24,
                    start_time=0.0,
                    log_path=files.status_log,
                )

            # Raw output should contain OSC 8 hyperlink sequences
            self.assertIn("\033]8;;file://", output)
            # Should contain the absolute path to the file
            self.assertIn("02_planning/plan.md", output)

    def test_render_phase_log_entries_do_not_contain_osc8_hyperlinks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)

            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.status_log.write_text(
                "2026-03-21 11:20:05  planning\n", encoding="utf-8"
            )
            files.created_files_log.write_text(
                "2026-03-21 11:20:08  02_planning/plan.md\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = monitor.render(
                    session_name="session-x",
                    files=files,
                    agents={},
                    width=60,
                    height=24,
                    start_time=0.0,
                    log_path=files.status_log,
                )

            # Split output to find phase event lines vs file event lines
            lines = output.split("\n")
            phase_line = ""
            file_line = ""
            for line in lines:
                if "> planning" in line:
                    phase_line = line
                # Look for file entry line by checking for the relative path in the line
                # (accounting for OSC 8 escape sequences that may wrap it)
                if "02_planning/plan.md" in line and "+ " in line:
                    file_line = line

            # Phase events should NOT contain OSC 8
            self.assertNotIn("\033]8;;", phase_line)

            # File events SHOULD contain OSC 8
            self.assertIn("\033]8;;", file_line)

    def test_strip_ansi_removes_osc8_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            files = _make_test_files(feature_dir)

            files.state.write_text('{"phase": "planning"}', encoding="utf-8")
            files.runtime_state.write_text('{"primary": {}}', encoding="utf-8")
            files.created_files_log.write_text(
                "2026-03-21 11:20:08  02_planning/plan.md\n",
                encoding="utf-8",
            )

            with patch("agentmux.monitor.render_module.time.time", return_value=0.0):
                output = monitor.render(
                    session_name="session-x",
                    files=files,
                    agents={},
                    width=60,
                    height=24,
                    start_time=0.0,
                    log_path=files.status_log,
                )

            stripped = self._strip_ansi(output)

            # Stripped output should not contain OSC 8 sequences
            self.assertNotIn("\033]8;;", stripped)
            self.assertNotIn("\033\\", stripped)
            # But should still contain the visible path text
            self.assertIn("02_planning/plan.md", stripped)

    def test_render_shows_session_name_in_footer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"

            state_path.write_text('{"phase": "implementing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")

            output = self._strip_ansi(self._render(feature_dir, width=40, height=18))

            self.assertIn("session-x", output)

    def test_render_uses_issue_title_when_present_in_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text(
                '{"phase": "implementing", "issue_title": "Fix auth bypass bug"}',
                encoding="utf-8",
            )
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            requirements_path.write_text(
                (
                    "# Requirements\n\n## Initial Request\n"
                    "fallback description from requirements\n"
                ),
                encoding="utf-8",
            )

            output = self._strip_ansi(self._render(feature_dir, width=40, height=18))

            self.assertIn("Fix auth bypass bug", output)
            self.assertNotIn("fallback description", output)

    def test_render_falls_back_to_requirements_when_no_issue_title(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            runtime_state_path = feature_dir / "runtime_state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text('{"phase": "implementing"}', encoding="utf-8")
            runtime_state_path.write_text('{"primary": {}}', encoding="utf-8")
            requirements_path.write_text(
                (
                    "# Requirements\n\n## Initial Request\n"
                    "build a todo app with filters\n"
                ),
                encoding="utf-8",
            )

            output = self._strip_ansi(self._render(feature_dir, width=40, height=18))

            self.assertIn("build a todo app", output)

    def test_read_session_summary_prefers_issue_title(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text(
                '{"issue_title": "GitHub Issue Title"}', encoding="utf-8"
            )
            requirements_path.write_text(
                "# Requirements\n\n## Initial Request\nFallback text\n",
                encoding="utf-8",
            )

            result = read_session_summary(state_path)
            self.assertEqual("GitHub Issue Title", result)

    def test_read_session_summary_falls_back_to_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text('{"phase": "planning"}', encoding="utf-8")
            requirements_path.write_text(
                "# Requirements\n\n## Initial Request\nFallback text\n",
                encoding="utf-8",
            )

            result = read_session_summary(state_path)
            self.assertEqual("Fallback text", result)

    def test_read_session_summary_handles_empty_issue_title(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            state_path = feature_dir / "state.json"
            requirements_path = feature_dir / "requirements.md"

            state_path.write_text('{"issue_title": ""}', encoding="utf-8")
            requirements_path.write_text(
                "# Requirements\n\n## Initial Request\nFallback text\n",
                encoding="utf-8",
            )

            result = read_session_summary(state_path)
            self.assertEqual("Fallback text", result)

    def test_monitor_file_event_patterns_contains_all_expected_patterns(self) -> None:
        from agentmux.monitor.state_reader import MONITOR_FILE_EVENT_PATTERNS

        expected = {
            "requirements.md",
            "01_product_management/analysis.md",
            "02_planning/plan.md",
            "02_planning/tasks.md",
            "03_research/code-*/summary.md",
            "03_research/code-*/detail.md",
            "03_research/code-*/done",
            "03_research/web-*/summary.md",
            "03_research/web-*/detail.md",
            "03_research/web-*/done",
            "04_design/design.md",
            "05_implementation/done_*",
            "06_review/review.md",
            "06_review/fix_request.md",
            "08_completion/changes.md",
            "08_completion/approval.json",
        }
        for pattern in expected:
            self.assertIn(pattern, MONITOR_FILE_EVENT_PATTERNS)

    def test_event_labels_contains_all_expected_keys(self) -> None:
        expected_keys = {
            "feature_created",
            "resumed",
            "plan_written",
            "design_written",
            "research_dispatched",
            "research_complete",
            "web_research_dispatched",
            "web_research_complete",
            "implementation_started",
            "implementation_completed",
            "review_written",
            "fix_requested",
            "fix_completed",
            "approved",
            "changes_requested",
            "plan_approved",
            "confirmation_sent",
            "pm_completed",
        }
        for key in expected_keys:
            self.assertIn(key, EVENT_LABELS)
            self.assertIsInstance(EVENT_LABELS[key], str)
            self.assertTrue(EVENT_LABELS[key])  # non-empty

    def test_role_display_label_dispatch_for_all_known_roles(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            fd = Path(td)
            (fd / "state.json").write_text(
                '{"phase": "implementing"}', encoding="utf-8"
            )

            self.assertEqual(
                role_display_label(fd, "architect"), "[architect] planning"
            )
            self.assertEqual(
                role_display_label(fd, "product-manager"), "[product-manager] analysis"
            )
            self.assertEqual(role_display_label(fd, "planner"), "[planner] planning")
            self.assertEqual(
                role_display_label(fd, "reviewer_logic"), "[reviewer_logic] logic"
            )
            self.assertEqual(
                role_display_label(fd, "reviewer_quality"), "[reviewer_quality] quality"
            )
            self.assertEqual(
                role_display_label(fd, "reviewer_expert"), "[reviewer_expert] expert"
            )
            self.assertEqual(
                role_display_label(fd, "code-researcher", task_id="caching"),
                "[code-researcher] caching",
            )
            self.assertEqual(
                role_display_label(fd, "web-researcher", task_id="api-docs"),
                "[web-researcher] api-docs",
            )
            # unknown role without task_id
            self.assertEqual(role_display_label(fd, "unknown-role"), "[unknown-role]")
            # unknown role with task_id falls back to showing the id
            self.assertEqual(
                role_display_label(fd, "unknown-role", task_id=3), "[unknown-role] 3"
            )

    def test_role_display_label_new_reviewer_roles_have_detail(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            fd = Path(td)
            (fd / "state.json").write_text('{"phase": "reviewing"}', encoding="utf-8")

            logic_label = role_display_label(fd, "reviewer_logic")
            quality_label = role_display_label(fd, "reviewer_quality")
            expert_label = role_display_label(fd, "reviewer_expert")

            self.assertIn("logic", logic_label)
            self.assertIn("quality", quality_label)
            self.assertIn("expert", expert_label)


if __name__ == "__main__":
    unittest.main()
