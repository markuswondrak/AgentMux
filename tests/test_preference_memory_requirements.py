from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentmux.workflow.preference_memory import (
    apply_preference_entries,
    normalize_preference_bullet,
)


class PreferenceMemoryRequirementsTests(unittest.TestCase):
    def test_normalization_handles_whitespace_bullets_and_case(self) -> None:
        left = normalize_preference_bullet("  -   Prefer   Pytest   fixtures ")
        right = normalize_preference_bullet("* prefer pytest fixtures")

        self.assertEqual(left, right)

    def test_apply_preference_entries_appends_bullets_under_section(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            entries = [
                {"target_role": "coder", "bullet": "- Prefer focused test cases"},
                {"target_role": "coder", "bullet": " -  keep function scope tight "},
                {"target_role": "architect", "bullet": "- Keep plans executable"},
            ]

            apply_preference_entries(project_dir, entries)

            coder_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            architect_prompt = (
                project_dir / ".agentmux" / "prompts" / "agents" / "architect.md"
            )
            self.assertTrue(coder_prompt.exists())
            coder_text = coder_prompt.read_text(encoding="utf-8")
            self.assertIn("## Approved Preferences", coder_text)
            self.assertIn("- Prefer focused test cases", coder_text)
            self.assertIn("- keep function scope tight", coder_text)
            self.assertTrue(architect_prompt.exists())
            self.assertIn(
                "- Keep plans executable",
                architect_prompt.read_text(encoding="utf-8"),
            )

    def test_apply_preference_entries_deduplicates_bullets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            coder_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            coder_prompt.parent.mkdir(parents=True, exist_ok=True)
            coder_prompt.write_text(
                "## Approved Preferences\n- Prefer focused test cases\n",
                encoding="utf-8",
            )

            entries = [
                {"target_role": "coder", "bullet": "Prefer focused test cases"},
                {"target_role": "coder", "bullet": "* Prefer focused TEST cases"},
                {"target_role": "coder", "bullet": "- New unique bullet"},
            ]
            apply_preference_entries(project_dir, entries)

            coder_text = coder_prompt.read_text(encoding="utf-8")
            self.assertEqual(1, coder_text.count("- Prefer focused test cases"))
            self.assertIn("- New unique bullet", coder_text)

    def test_apply_preference_entries_deduplicates_within_call(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            entries = [
                {"target_role": "coder", "bullet": "- Keep it simple"},
                {"target_role": "coder", "bullet": "* keep it simple"},
            ]
            apply_preference_entries(project_dir, entries)

            coder_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            coder_text = coder_prompt.read_text(encoding="utf-8")
            self.assertEqual(1, coder_text.count("- Keep it simple"))

    def test_apply_preference_entries_creates_file_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            coder_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"

            self.assertFalse(coder_prompt.exists())

            apply_preference_entries(
                project_dir,
                [{"target_role": "coder", "bullet": "- Validate inputs early"}],
            )

            coder_text = coder_prompt.read_text(encoding="utf-8")
            self.assertTrue(coder_prompt.exists())
            self.assertIn("## Approved Preferences", coder_text)
            self.assertIn("- Validate inputs early", coder_text)

    def test_apply_preference_entries_preserves_existing_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            coder_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            coder_prompt.parent.mkdir(parents=True, exist_ok=True)
            coder_prompt.write_text(
                "<!-- Project-specific instructions for the coder role. -->\n",
                encoding="utf-8",
            )

            apply_preference_entries(
                project_dir,
                [{"target_role": "coder", "bullet": "- New preference"}],
            )

            coder_text = coder_prompt.read_text(encoding="utf-8")
            self.assertIn(
                "<!-- Project-specific instructions for the coder role. -->", coder_text
            )
            self.assertIn("- New preference", coder_text)

    def test_apply_preference_entries_empty_list_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            apply_preference_entries(project_dir, [])
            prompts_dir = project_dir / ".agentmux" / "prompts" / "agents"
            self.assertFalse(prompts_dir.exists())


if __name__ == "__main__":
    unittest.main()
