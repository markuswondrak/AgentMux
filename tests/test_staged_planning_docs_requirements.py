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
