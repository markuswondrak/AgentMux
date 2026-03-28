from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from agentmux.workflow.prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_coder_subplan_prompt,
    build_reviewer_prompt,
)
from agentmux.sessions.state_store import create_feature_files, load_runtime_files


class TasksRequirementsTests(unittest.TestCase):
    def test_command_prompt_templates_no_longer_include_docs_agent_handoff_template(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        command_templates = sorted(path.name for path in (repo_root / "agentmux/prompts/commands").glob("*.md"))

        self.assertNotIn("docs.md", command_templates)

    def test_built_in_prompt_templates_use_bracketed_value_placeholders(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        template_paths = sorted(
            [*(repo_root / "agentmux/prompts/agents").glob("*.md"), *(repo_root / "agentmux/prompts/commands").glob("*.md")]
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

            files = create_feature_files(project_dir, feature_dir, "add tasks list", "session")
            loaded = load_runtime_files(project_dir, feature_dir)

            self.assertEqual(feature_dir / "02_planning" / "tasks.md", files.tasks)
            self.assertEqual(feature_dir / "02_planning" / "tasks.md", loaded.tasks)
            self.assertEqual(feature_dir / "created_files.log", files.created_files_log)
            self.assertEqual(feature_dir / "created_files.log", loaded.created_files_log)
            self.assertFalse(files.plan.exists())
            self.assertFalse(files.tasks.exists())
            self.assertFalse(files.design.exists())
            self.assertFalse(files.review.exists())
            self.assertFalse(files.fix_request.exists())
            self.assertFalse(files.created_files_log.exists())

    def test_architect_and_coder_prompts_reference_plan_meta_and_done_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "add tasks list", "session")

            architect_prompt = build_architect_prompt(files)
            coder_prompt = build_coder_subplan_prompt(files, feature_dir / "02_planning" / "plan_1.md", 1)

            self.assertIn("write the final plan to `02_planning/plan.md`", architect_prompt)
            self.assertIn("also write `02_planning/tasks.md`", architect_prompt)
            self.assertIn("also write `02_planning/execution_plan.json`", architect_prompt)
            self.assertIn("write `02_planning/plan_meta.json`", architect_prompt)
            self.assertIn(
                "Documentation updates must be captured as explicit plan and task items in `02_planning/plan.md`, every `02_planning/plan_<N>.md`, and `02_planning/tasks.md`.",
                architect_prompt,
            )
            self.assertIn("needs_design", architect_prompt)
            self.assertIn("needs_docs", architect_prompt)
            self.assertIn("doc_files", architect_prompt)
            self.assertIn("empty list when `needs_docs` is `false`", architect_prompt)
            self.assertIn("Do not treat `needs_docs` as a workflow switch", architect_prompt)
            self.assertIn("Phase 1: Foundation & Interfaces", architect_prompt)
            self.assertIn("Phase 2: Parallel Implementation", architect_prompt)
            self.assertIn("Phase 3: Integration & Validation", architect_prompt)
            self.assertIn("Scope", architect_prompt)
            self.assertIn("Owned files/modules", architect_prompt)
            self.assertIn("Dependencies", architect_prompt)
            self.assertIn("Isolation", architect_prompt)
            self.assertIn("conflict mapping", architect_prompt.lower())
            self.assertIn("owned files/modules must be disjoint", architect_prompt)
            self.assertIn("merge that work into one sub-plan or move the overlapping portion into a serial Phase 3 integration step", architect_prompt)
            self.assertIn("shared mutable artifacts", architect_prompt)
            self.assertIn("task ownership unambiguous", architect_prompt)
            self.assertIn("must belong only to that sub-plan's owned files/modules", architect_prompt)
            self.assertIn("technical debt", architect_prompt.lower())
            self.assertNotIn("legacy flat `plan.md` parsing fallback", architect_prompt)
            self.assertNotIn("Empty file-set intersection is a hint for parallelization", architect_prompt)
            self.assertIn("05_implementation/done_1", coder_prompt)
            self.assertIn("Do not update state.json", coder_prompt)
            self.assertIn("TDD protocol", coder_prompt)
            self.assertIn("fail before implementation (Red)", coder_prompt)
            self.assertIn("until the tests pass (Green)", coder_prompt)
            self.assertIn("Follow the phase order from the active plan strictly", coder_prompt)
            self.assertIn("Complete one task from `02_planning/tasks.md` at a time", coder_prompt)
            self.assertIn("check off that task before moving to the next one", coder_prompt)

    def test_coder_subplan_prompt_keeps_contract_and_subplan_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "subplan coder contract", "session")

            prompt = build_coder_subplan_prompt(files, feature_dir / "02_planning" / "plan_2.md", 2)

            self.assertIn("02_planning/plan_2.md", prompt)
            self.assertIn("05_implementation/done_2", prompt)
            self.assertIn("TDD protocol", prompt)
            self.assertIn("fail before implementation (Red)", prompt)
            self.assertIn("until the tests pass (Green)", prompt)
            self.assertIn("Follow the phase order from the active plan strictly", prompt)
            self.assertIn("Complete one task from `02_planning/tasks.md` at a time", prompt)
            self.assertIn("check off that task before moving to the next one", prompt)

    def test_coder_and_reviewer_prompts_keep_docs_tasks_in_main_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "docs ownership", "session")

            coder_prompt = build_coder_subplan_prompt(files, feature_dir / "02_planning" / "plan_1.md", 1)
            reviewer_agent_prompt = build_reviewer_prompt(files)
            reviewer_review_prompt = build_reviewer_prompt(files, is_review=True)

            self.assertIn(
                "When `02_planning/tasks.md` includes documentation tasks, complete them as part of implementation in this coder step.",
                coder_prompt,
            )
            self.assertIn("Do not defer documentation to a separate docs agent or post-review docs phase.", coder_prompt)

            self.assertIn(
                "Treat planned documentation updates as required implementation scope during review; do not defer them to a separate phase or agent.",
                reviewer_agent_prompt,
            )
            self.assertIn(
                "Verify documentation tasks listed in `02_planning/tasks.md` are complete when they are part of the approved scope.",
                reviewer_review_prompt,
            )

    def test_change_prompt_references_files_instead_of_embedding_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()

            files = create_feature_files(project_dir, feature_dir, "add tasks list", "session")
            files.changes.parent.mkdir(parents=True, exist_ok=True)
            files.plan.parent.mkdir(parents=True, exist_ok=True)
            files.changes.write_text("change request", encoding="utf-8")
            files.plan.write_text("# Plan\n\n1. Example step\n", encoding="utf-8")
            files.tasks.write_text("# Tasks\n\n1. Example task\n", encoding="utf-8")

            prompt = build_change_prompt(files)

            self.assertIn("Read these files first:", prompt)
            self.assertIn("- requirements.md", prompt)
            self.assertIn("- 02_planning/plan.md", prompt)
            self.assertIn("- 02_planning/tasks.md", prompt)
            self.assertIn("- 08_completion/changes.md", prompt)
            self.assertIn("02_planning/execution_plan.json", prompt)
            self.assertIn("02_planning/plan_meta.json", prompt)
            self.assertIn(
                "Documentation updates must be captured as explicit plan and task items in `02_planning/plan.md`, every `02_planning/plan_<N>.md`, and `02_planning/tasks.md`.",
                prompt,
            )
            self.assertIn("needs_design", prompt)
            self.assertIn("needs_docs", prompt)
            self.assertIn("doc_files", prompt)
            self.assertIn("empty list when `needs_docs` is `false`", prompt)
            self.assertIn("Do not treat `needs_docs` as a workflow switch", prompt)
            self.assertIn("Phase 1: Foundation & Interfaces", prompt)
            self.assertIn("Phase 2: Parallel Implementation", prompt)
            self.assertIn("Phase 3: Integration & Validation", prompt)
            self.assertIn("Scope", prompt)
            self.assertIn("Owned files/modules", prompt)
            self.assertIn("Dependencies", prompt)
            self.assertIn("Isolation", prompt)
            self.assertIn("conflict mapping", prompt.lower())
            self.assertIn("owned files/modules must be disjoint", prompt)
            self.assertIn("merge that work into one sub-plan or move the overlapping portion into a serial Phase 3 integration step", prompt)
            self.assertIn("shared mutable artifacts", prompt)
            self.assertIn("task ownership unambiguous", prompt)
            self.assertIn("must belong only to that sub-plan's owned files/modules", prompt)
            self.assertIn("technical debt", prompt.lower())
            self.assertNotIn("should be treated as parallelizable unless a precise technical conflict is documented", prompt)
            self.assertNotIn("1. Example task", prompt)

    def test_architect_prompt_no_longer_accepts_review_mode_and_reviewer_prompt_handles_review(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "review split", "session")

            with self.assertRaises(TypeError):
                build_architect_prompt(files, is_review=True)  # type: ignore[call-arg]

            review_prompt = build_reviewer_prompt(files, is_review=True)
            self.assertIn("reviewer agent in review mode", review_prompt)


if __name__ == "__main__":
    unittest.main()
