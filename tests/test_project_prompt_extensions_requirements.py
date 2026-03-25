from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_code_researcher_prompt,
    build_coder_prompt,
    build_coder_subplan_prompt,
    build_confirmation_prompt,
    build_designer_prompt,
    build_docs_prompt,
    build_fix_prompt,
    build_product_manager_prompt,
    build_reviewer_prompt,
    build_web_researcher_prompt,
)
from agentmux.state import create_feature_files


class ProjectPromptExtensionsRequirementsTests(unittest.TestCase):
    def _write_project_prompt(self, project_dir: Path, subdir: str, name: str, content: str) -> None:
        path = project_dir / ".agentmux" / "prompts" / subdir / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _create_research_topic(
        self,
        feature_dir: Path,
        topic_dir_name: str,
        *,
        done: bool,
        include_detail: bool = True,
    ) -> None:
        topic_dir = feature_dir / "03_research" / topic_dir_name
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "summary.md").write_text(f"# Summary for {topic_dir_name}\n", encoding="utf-8")
        if include_detail:
            (topic_dir / "detail.md").write_text(f"# Detail for {topic_dir_name}\n", encoding="utf-8")
        if done:
            (topic_dir / "done").write_text("", encoding="utf-8")

    def test_builtin_templates_expose_project_instruction_placeholder_before_constraints(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        template_paths = [
            repo_root / "agentmux/prompts/agents/architect.md",
            repo_root / "agentmux/prompts/agents/coder.md",
            repo_root / "agentmux/prompts/agents/reviewer.md",
            repo_root / "agentmux/prompts/agents/product-manager.md",
            repo_root / "agentmux/prompts/agents/code-researcher.md",
            repo_root / "agentmux/prompts/agents/web-researcher.md",
            repo_root / "agentmux/prompts/agents/designer.md",
            repo_root / "agentmux/prompts/commands/review.md",
            repo_root / "agentmux/prompts/commands/fix.md",
            repo_root / "agentmux/prompts/commands/confirmation.md",
            repo_root / "agentmux/prompts/commands/change.md",
            repo_root / "agentmux/prompts/commands/docs.md",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path)):
                template = template_path.read_text(encoding="utf-8")
                self.assertIn("{project_instructions}", template)
                self.assertIn("Constraints:", template)
                self.assertLess(template.index("{project_instructions}"), template.index("Constraints:"))

    def test_builders_inject_project_prompt_extensions_before_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "project-specific prompts", "session")

            cases: list[tuple[str, str, str, object]] = [
                ("agents", "architect", "EXT-ARCHITECT", lambda runtime: build_architect_prompt(runtime)),
                ("agents", "product-manager", "EXT-PM", lambda runtime: build_product_manager_prompt(runtime)),
                ("agents", "reviewer", "EXT-REVIEWER", lambda runtime: build_reviewer_prompt(runtime)),
                ("agents", "coder", "EXT-CODER", lambda runtime: build_coder_prompt(runtime)),
                ("agents", "designer", "EXT-DESIGNER", lambda runtime: build_designer_prompt(runtime)),
                (
                    "agents",
                    "coder",
                    "EXT-CODER",
                    lambda runtime: build_coder_subplan_prompt(runtime, feature_dir / "02_planning" / "subplan_1.md", 1),
                ),
                (
                    "agents",
                    "code-researcher",
                    "EXT-CODE-RESEARCHER",
                    lambda runtime: build_code_researcher_prompt("topic-a", runtime),
                ),
                (
                    "agents",
                    "web-researcher",
                    "EXT-WEB-RESEARCHER",
                    lambda runtime: build_web_researcher_prompt("topic-b", runtime),
                ),
                ("commands", "review", "EXT-REVIEW-COMMAND", lambda runtime: build_reviewer_prompt(runtime, True)),
                ("commands", "fix", "EXT-FIX", lambda runtime: build_fix_prompt(runtime)),
                ("commands", "docs", "EXT-DOCS", lambda runtime: build_docs_prompt(runtime)),
                (
                    "commands",
                    "confirmation",
                    "EXT-CONFIRMATION",
                    lambda runtime: build_confirmation_prompt(runtime),
                ),
                ("commands", "change", "EXT-CHANGE", lambda runtime: build_change_prompt(runtime)),
            ]

            for subdir, name, marker, _ in cases:
                self._write_project_prompt(project_dir, subdir, name, f"Project extension marker: {marker}\n")

            with patch(
                "agentmux.prompts.subprocess.run",
                return_value=subprocess.CompletedProcess(args=["git", "status", "--porcelain"], returncode=0, stdout="", stderr=""),
            ):
                for _, _, marker, builder in cases:
                    with self.subTest(marker=marker):
                        prompt = builder(files)
                        self.assertIn(marker, prompt)
                        self.assertIn("Constraints:", prompt)
                        self.assertLess(prompt.index(marker), prompt.index("Constraints:"))

    def test_project_prompts_with_curly_braces_do_not_break_template_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "project-specific prompts", "session")

            injected = "Literal braces: {something} and orphan close brace } and open brace {\n"
            self._write_project_prompt(project_dir, "agents", "coder", injected)

            prompt = build_coder_prompt(files)

            self.assertIn(injected, prompt)
            self.assertNotIn("{project_instructions}", prompt)

    def test_coder_prompt_includes_completed_research_references(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "research handoff", "session")

            self._create_research_topic(feature_dir, "web-openai-models", done=True, include_detail=False)
            self._create_research_topic(feature_dir, "code-auth-module", done=True, include_detail=True)
            self._create_research_topic(feature_dir, "code-incomplete-topic", done=False, include_detail=True)

            prompt = build_coder_prompt(files)

            self.assertIn("Research handoff (read before new exploration):", prompt)
            self.assertIn("03_research/code-auth-module/summary.md", prompt)
            self.assertIn("03_research/code-auth-module/detail.md", prompt)
            self.assertIn("03_research/web-openai-models/summary.md", prompt)
            self.assertNotIn("03_research/web-openai-models/detail.md", prompt)
            self.assertNotIn("03_research/code-incomplete-topic/summary.md", prompt)
            self.assertLess(
                prompt.index("03_research/code-auth-module/summary.md"),
                prompt.index("03_research/web-openai-models/summary.md"),
            )

    def test_coder_subplan_prompt_includes_completed_research_references(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "research handoff", "session")

            self._create_research_topic(feature_dir, "web-routing", done=True, include_detail=True)
            self._create_research_topic(feature_dir, "code-db-indexes", done=True, include_detail=True)

            prompt = build_coder_subplan_prompt(files, feature_dir / "02_planning" / "plan_1.md", 1)

            self.assertIn("Research handoff (read before new exploration):", prompt)
            self.assertIn("03_research/code-db-indexes/summary.md", prompt)
            self.assertIn("03_research/code-db-indexes/detail.md", prompt)
            self.assertIn("03_research/web-routing/summary.md", prompt)
            self.assertIn("03_research/web-routing/detail.md", prompt)

    def test_coder_prompts_omit_research_handoff_when_no_completed_topics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "research handoff", "session")

            self._create_research_topic(feature_dir, "code-incomplete-topic", done=False, include_detail=True)

            prompt = build_coder_prompt(files)
            subplan_prompt = build_coder_subplan_prompt(files, feature_dir / "02_planning" / "plan_1.md", 1)

            self.assertNotIn("Research handoff (read before new exploration):", prompt)
            self.assertNotIn("Research handoff (read before new exploration):", subplan_prompt)
            self.assertNotIn("03_research/code-incomplete-topic/summary.md", prompt)
            self.assertNotIn("03_research/code-incomplete-topic/summary.md", subplan_prompt)


if __name__ == "__main__":
    unittest.main()
