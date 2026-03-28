from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.sessions.state_store import create_feature_files
from agentmux.workflow import prompts as prompts_module


class SessionIncludeTests(unittest.TestCase):
    def test_mandatory_include_resolves_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)
            (feature_dir / "context.md").write_text("ctx content\n", encoding="utf-8")

            rendered = prompts_module._expand_session_includes("Header\n[[include:context.md]]\n", feature_dir)

            self.assertIn("ctx content", rendered)
            self.assertNotIn("[[include:context.md]]", rendered)

    def test_mandatory_include_raises_for_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(FileNotFoundError):
                prompts_module._expand_session_includes("[[include:missing.md]]", feature_dir)

    def test_optional_include_resolves_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)
            (feature_dir / "04_design" / "design.md").parent.mkdir(parents=True, exist_ok=True)
            (feature_dir / "04_design" / "design.md").write_text("design details", encoding="utf-8")

            rendered = prompts_module._expand_session_includes(
                "A\n[[include-optional:04_design/design.md]]\nB",
                feature_dir,
            )

            self.assertIn("design details", rendered)
            self.assertNotIn("[[include-optional:04_design/design.md]]", rendered)

    def test_optional_include_resolves_to_empty_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)

            rendered = prompts_module._expand_session_includes(
                "A\n[[include-optional:04_design/design.md]]\nB",
                feature_dir,
            )

            self.assertEqual("A\n\nB", rendered)

    def test_placeholder_inside_include_resolves_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)
            (feature_dir / "02_planning").mkdir(parents=True, exist_ok=True)
            (feature_dir / "02_planning" / "plan_1.md").write_text("# Plan 1\n", encoding="utf-8")

            template = "[[include:[[placeholder:plan_file]]]]"
            rendered = prompts_module._render_template(template, {"plan_file": "02_planning/plan_1.md"})
            expanded = prompts_module._expand_session_includes(rendered, feature_dir)

            self.assertEqual("# Plan 1\n", expanded)

    def test_multiple_includes_in_one_template_all_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td) / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)
            (feature_dir / "a.md").write_text("A", encoding="utf-8")
            (feature_dir / "b.md").write_text("B", encoding="utf-8")

            rendered = prompts_module._expand_session_includes(
                "[[include:a.md]] + [[include:b.md]]",
                feature_dir,
            )

            self.assertEqual("A + B", rendered)

    def test_build_architect_prompt_inlines_include_content_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            prompts_dir = tmp_path / "prompts"
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "include e2e", "session-x")

            architect_template = prompts_dir / "agents" / "architect.md"
            architect_template.parent.mkdir(parents=True, exist_ok=True)
            architect_template.write_text(
                "Session [[placeholder:feature_dir]]\n[[include:context.md]]\n[[placeholder:project_instructions]]\nConstraints:\n",
                encoding="utf-8",
            )

            with patch.object(prompts_module, "PROMPTS_DIR", prompts_dir):
                prompt = prompts_module.build_architect_prompt(files)

            self.assertIn("# Context", prompt)
            self.assertNotIn("[[include:context.md]]", prompt)


if __name__ == "__main__":
    unittest.main()
