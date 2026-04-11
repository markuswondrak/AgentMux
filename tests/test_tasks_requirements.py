from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from agentmux.sessions.state_store import create_feature_files, load_runtime_files
from agentmux.workflow.prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_coder_subplan_prompt,
    build_planner_prompt,
    build_reviewer_prompt,
)


class TasksRequirementsTests(unittest.TestCase):
    def _write_coder_inputs(
        self, feature_dir: Path, plan_name: str = "plan_1.md"
    ) -> None:
        planning_dir = feature_dir / "04_planning"
        planning_dir.mkdir(parents=True, exist_ok=True)
        (planning_dir / plan_name).write_text(f"## {plan_name}\n", encoding="utf-8")

        # Extract plan index from plan_name (e.g., "plan_1.md" -> 1)
        match = re.search(r"plan_(\d+)\.md", plan_name)
        plan_index = int(match.group(1)) if match else 1

        # Create per-plan tasks file (tasks_{N}.md)
        tasks_file = planning_dir / f"tasks_{plan_index}.md"
        tasks_file.write_text(
            f"# Tasks for {plan_name}\n\n- [ ] one task\n", encoding="utf-8"
        )

        # Create required files for prompts
        (feature_dir / "context.md").write_text("# Context", encoding="utf-8")
        architecting_dir = feature_dir / "02_architecting"
        architecting_dir.mkdir(parents=True, exist_ok=True)
        (architecting_dir / "architecture.md").write_text(
            "# Architecture", encoding="utf-8"
        )

    def test_command_prompt_templates_no_longer_include_docs_agent_handoff_template(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command_templates = sorted(
            path.name
            for path in (repo_root / "src/agentmux/prompts/commands").glob("*.md")
        )

        self.assertNotIn("docs.md", command_templates)

    def test_built_in_prompt_templates_use_bracketed_value_placeholders(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        template_paths = sorted(
            [
                *(repo_root / "src/agentmux/prompts/agents").glob("*.md"),
                *(repo_root / "src/agentmux/prompts/commands").glob("*.md"),
            ]
        )
        legacy_placeholder_pattern = re.compile(r"\{[a-z_][a-z0-9_]*\}")

        for template_path in template_paths:
            with self.subTest(template=str(template_path)):
                template = template_path.read_text(encoding="utf-8")
                self.assertNotRegex(template, legacy_placeholder_pattern)

    def test_runtime_files_include_tasks_and_placeholders_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "add tasks list", "session"
            )
            loaded = load_runtime_files(project_dir, feature_dir)

            self.assertEqual(feature_dir / "04_planning" / "tasks.md", files.tasks)
            self.assertEqual(feature_dir / "04_planning" / "tasks.md", loaded.tasks)
            self.assertEqual(feature_dir / "created_files.log", files.created_files_log)
            self.assertEqual(
                feature_dir / "created_files.log", loaded.created_files_log
            )
            self.assertFalse(files.plan.exists())
            self.assertFalse(files.tasks.exists())
            self.assertFalse(files.design.exists())
            self.assertFalse(files.review.exists())
            self.assertFalse(files.fix_request.exists())
            self.assertFalse(files.created_files_log.exists())

    def test_architect_and_coder_prompts_reference_plan_meta_and_done_marker(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "add tasks list", "session"
            )
            self._write_coder_inputs(feature_dir, "plan_1.md")

            architect_prompt = build_architect_prompt(files)
            planner_prompt = build_planner_prompt(files)
            coder_prompt = build_coder_subplan_prompt(
                files, feature_dir / "04_planning" / "plan_1.md", 1
            )

            # Architect focuses on technical design — must NOT contain plan file
            # instructions (those belong to the planner)
            self.assertNotIn(
                "write the final plan to `04_planning/plan.md`", architect_prompt
            )
            self.assertNotIn("also write per-plan task files", architect_prompt)
            self.assertNotIn(
                "also write `04_planning/execution_plan.yaml`", architect_prompt
            )
            self.assertNotIn("write `04_planning/plan_meta.json`", architect_prompt)
            self.assertNotIn("Phase 1: Foundation & Interfaces", architect_prompt)
            self.assertNotIn("Phase 2: Parallel Implementation", architect_prompt)
            self.assertNotIn("legacy flat `plan.md` parsing fallback", architect_prompt)
            self.assertNotIn(
                "Empty file-set intersection is a hint for parallelization",
                architect_prompt,
            )

            # Architect must describe technical design output (architecture.md)
            self.assertIn("02_architecting/architecture.md", architect_prompt)
            self.assertIn("Components", architect_prompt)
            self.assertIn("Interfaces", architect_prompt)

            # Planner owns execution planning — check streamlined content
            self.assertIn("04_planning/plan.yaml", planner_prompt)
            self.assertIn("02_architecting/architecture.md", planner_prompt)
            self.assertIn("Phase 1 (Serial - Foundation)", planner_prompt)
            self.assertIn("Phase 2 (Parallel - Implementation)", planner_prompt)
            self.assertIn("Phase 3 (Serial - Integration)", planner_prompt)
            self.assertIn("Scope", planner_prompt)
            self.assertIn("Owned Files/Modules", planner_prompt)
            self.assertIn("Dependencies", planner_prompt)
            self.assertIn("Isolation", planner_prompt)
            self.assertIn("Final Artifact Generation", planner_prompt)
            self.assertNotIn("plan_meta.json", planner_prompt)

            self.assertIn("06_implementation/done_1", coder_prompt)
            self.assertIn("Do not update state.json", coder_prompt)
            self.assertIn("TDD protocol", coder_prompt)
            self.assertIn("fail before implementation (Red)", coder_prompt)
            self.assertIn("until the tests pass (Green)", coder_prompt)
            self.assertIn("Follow the plan's phase order strictly", coder_prompt)
            self.assertIn(
                "Work atomically through the task checklist: "
                "Complete one task at a time",
                coder_prompt,
            )
            self.assertIn(
                "check off that task before moving to the next one", coder_prompt
            )

    def test_coder_subplan_prompt_keeps_contract_and_subplan_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "subplan coder contract", "session"
            )
            self._write_coder_inputs(feature_dir, "plan_2.md")

            prompt = build_coder_subplan_prompt(
                files, feature_dir / "04_planning" / "plan_2.md", 2
            )

            self.assertIn("04_planning/plan_2.md", prompt)
            self.assertIn("06_implementation/done_2", prompt)
            self.assertIn("TDD protocol", prompt)
            self.assertIn("fail before implementation (Red)", prompt)
            self.assertIn("until the tests pass (Green)", prompt)
            self.assertIn("Follow the plan's phase order strictly", prompt)
            self.assertIn(
                "Work atomically through the task checklist: "
                "Complete one task at a time",
                prompt,
            )
            self.assertIn("check off that task before moving to the next one", prompt)

    def test_coder_and_reviewer_prompts_keep_docs_tasks_in_main_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "docs ownership", "session"
            )
            self._write_coder_inputs(feature_dir, "plan_1.md")

            coder_prompt = build_coder_subplan_prompt(
                files, feature_dir / "04_planning" / "plan_1.md", 1
            )
            reviewer_agent_prompt = build_reviewer_prompt(files)
            reviewer_review_prompt = build_reviewer_prompt(files, is_review=True)

            self.assertIn(
                "When the task checklist includes documentation tasks, "
                "complete them as part of implementation.",
                coder_prompt,
            )
            self.assertIn(
                "Do not defer documentation to a separate docs agent "
                "or post-review docs phase.",
                coder_prompt,
            )

            self.assertIn(
                "Treat planned documentation updates as required implementation scope",
                reviewer_agent_prompt,
            )
            self.assertIn(
                "Verify documentation tasks listed in `04_planning/tasks_<N>.md` "
                "are complete when they are part of the approved scope.",
                reviewer_review_prompt,
            )

    def test_change_prompt_inlines_required_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(
                project_dir, feature_dir, "add tasks list", "session"
            )
            files.changes.parent.mkdir(parents=True, exist_ok=True)
            files.plan.parent.mkdir(parents=True, exist_ok=True)
            files.changes.write_text("change request", encoding="utf-8")
            files.plan.write_text("# Plan\n\n1. Example step\n", encoding="utf-8")
            files.tasks.write_text("# Tasks\n\n1. Example task\n", encoding="utf-8")

            prompt = build_change_prompt(files)

            self.assertIn('<file path="requirements.md">', prompt)
            self.assertIn('<file path="04_planning/plan.md">', prompt)
            self.assertNotIn('<file path="04_planning/tasks.md">', prompt)
            self.assertIn('<file path="04_planning/changes.md">', prompt)
            self.assertIn("plan.yaml", prompt)
            self.assertNotIn("04_planning/plan_meta.json", prompt)
            self.assertIn(
                "Documentation updates must be captured as explicit tasks "
                "in the relevant sub-plan.",
                prompt,
            )
            self.assertIn("needs_design", prompt)
            self.assertIn("needs_docs", prompt)
            self.assertIn("doc_files", prompt)
            self.assertIn("Scope", prompt)
            self.assertIn("owned_files", prompt)
            self.assertIn("dependencies", prompt)
            self.assertIn("isolation_rationale", prompt)
            self.assertIn("conflict mapping", prompt.lower())
            self.assertIn("owned files/modules must be disjoint", prompt)
            self.assertIn(
                "merge that work into one sub-plan or move "
                "the overlapping portion into a serial group",
                prompt,
            )
            self.assertIn("shared mutable artifacts", prompt)
            self.assertIn("technical debt", prompt.lower())

    def test_architect_prompt_no_longer_accepts_review_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(
                project_dir, feature_dir, "review split", "session"
            )

            with self.assertRaises(TypeError):
                build_architect_prompt(files, is_review=True)  # type: ignore[call-arg]

            review_prompt = build_reviewer_prompt(files, is_review=True)
            self.assertIn(
                "Review the implementation against requirements", review_prompt
            )


if __name__ == "__main__":
    unittest.main()
