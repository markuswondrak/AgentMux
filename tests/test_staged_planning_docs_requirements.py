from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class StagedPlanningDocsRequirementsTests(unittest.TestCase):
    def _read_doc(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_prompts_doc_covers_staged_planning_contract(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("02_planning/execution_plan.json", text)
        self.assertIn("plan_<N>.md", text)
        self.assertIn("Scope", text)
        self.assertIn("Dependencies", text)
        self.assertIn("Isolation", text)
        self.assertIn("conflict mapping", text.lower())
        self.assertIn("enabling refactor", text.lower())
        self.assertIn("technical debt", text.lower())

    def test_prompts_doc_covers_two_stage_template_rendering(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("[[shared:", text)
        self.assertIn("[[placeholder:", text)
        self.assertIn("two-stage", text.lower())
        self.assertIn("template loading", text.lower())
        self.assertIn("render", text.lower())

    def test_prompts_doc_covers_coder_tdd_phase_and_atomic_contract(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("TDD protocol", text)
        self.assertIn("Red", text)
        self.assertIn("Green", text)
        self.assertIn("phase order", text.lower())
        self.assertIn("one task from `02_planning/tasks.md` at a time", text)

    def test_prompts_doc_describes_legacy_placeholder_compatibility(self) -> None:
        text = self._read_doc("docs/prompts.md")
        self.assertIn("legacy", text.lower())
        self.assertIn("{project_instructions}", text)

    def test_file_protocol_doc_covers_execution_groups_and_compatibility(self) -> None:
        text = self._read_doc("docs/file-protocol.md")
        self.assertIn("execution_plan.json", text)
        self.assertIn("execution groups", text.lower())
        self.assertIn("serial", text.lower())
        self.assertIn("parallel", text.lower())
        self.assertIn("legacy", text.lower())
        self.assertIn("plan_*.md", text)

    def test_monitor_doc_covers_staged_execution_progress(self) -> None:
        text = self._read_doc("docs/monitor.md")
        self.assertIn("execution group", text.lower())
        self.assertIn("serial", text.lower())
        self.assertIn("parallel", text.lower())
        self.assertIn("overall progress", text.lower())


if __name__ == "__main__":
    unittest.main()
