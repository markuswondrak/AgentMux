from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class StagedPlanningDocsRequirementsTests(unittest.TestCase):
    def _read_doc(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_prompts_doc_covers_staged_planning_contract(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("04_planning/execution_plan.yaml", text)
        self.assertIn("plan_<N>.md", text)
        self.assertIn("Scope", text)
        self.assertIn("Owned files/modules", text)
        self.assertIn("Dependencies", text)
        self.assertIn("Isolation", text)
        self.assertIn("conflict mapping", text.lower())
        self.assertIn("disjoint", text.lower())
        self.assertIn("shared mutable artifacts", text.lower())
        self.assertIn("exclusive ownership", text.lower())
        self.assertIn("enabling refactor", text.lower())
        self.assertIn("technical debt", text.lower())
        self.assertNotIn(
            "empty file-set intersection should be treated as parallelizable",
            text.lower(),
        )

    def test_prompts_doc_covers_three_stage_template_rendering(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("[[shared:", text)
        self.assertIn("[[placeholder:", text)
        self.assertIn("[[include:", text)
        self.assertIn("three-stage", text.lower())
        self.assertIn("template loading", text.lower())
        self.assertIn("render", text.lower())
        self.assertIn("session include expansion", text.lower())

    def test_prompts_doc_covers_coder_tdd_phase_and_atomic_contract(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("TDD protocol", text)
        self.assertIn("Red", text)
        self.assertIn("Green", text)
        self.assertIn("phase order", text.lower())
        self.assertIn(
            "one task from your assigned `04_planning/tasks_<N>.md` at a time", text
        )

    def test_prompts_doc_describes_strict_placeholder_rendering(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("[[placeholder:project_instructions]]", text)
        self.assertIn("Curly braces in project content stay literal", text)
        self.assertNotIn("{project_instructions}", text)

    def test_file_protocol_doc_covers_execution_groups_and_strict_scheduling(
        self,
    ) -> None:
        text = self._read_doc("docs/phases/04_planning.md")
        self.assertIn("execution_plan.yaml", text)
        self.assertIn("execution groups", text.lower())
        self.assertIn("serial", text.lower())
        self.assertIn("parallel", text.lower())
        self.assertIn("strict", text.lower())
        self.assertIn("YAML mapping", text)
        self.assertIn("`- file: plan_1.md`", text)
        self.assertIn("`name: Core setup`", text)

    def test_monitor_doc_covers_staged_execution_progress(self) -> None:
        text = self._read_doc("docs/monitor.md")
        self.assertIn("execution group", text.lower())
        self.assertIn("serial", text.lower())
        self.assertIn("parallel", text.lower())
        self.assertIn("overall progress", text.lower())

    def test_prompts_doc_no_longer_describes_docs_agent_prompt_builder(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertNotIn("build_docs_prompt()", text)
        self.assertNotIn("commands/docs.md", text)
        self.assertIn(
            "Documentation updates must be represented in planning artifacts", text
        )

    def test_workflow_docs_no_longer_reference_removed_docs_phase_markers(self) -> None:
        for relative_path in [
            "docs/file-protocol.md",
            "docs/phases/08_completion.md",
            "docs/session-resumption.md",
            "docs/monitor.md",
        ]:
            with self.subTest(path=relative_path):
                text = self._read_doc(relative_path)
                self.assertNotIn("`documenting`", text)
                self.assertNotIn("`docs_written`", text)
                self.assertNotIn("`07_docs`", text)
                self.assertNotIn("`docs_done`", text)

    def test_repo_docs_no_longer_list_removed_docs_role_or_phase(self) -> None:
        for relative_path, forbidden in [
            ("README.md", "\n  docs:\n"),
            ("docs/configuration.md", "\n  docs:\n"),
            ("CLAUDE.md", "→ verdict:pass → documenting? → completing"),
        ]:
            with self.subTest(path=relative_path):
                text = self._read_doc(relative_path)
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
