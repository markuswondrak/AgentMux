from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.workflow import prompts as prompts_module
from agentmux.workflow.prompts import (
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
from agentmux.sessions.state_store import create_feature_files


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

    def _write_builtin_template(self, prompts_dir: Path, subdir: str, name: str, content: str) -> None:
        path = prompts_dir / subdir / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_shared_fragment(self, prompts_dir: Path, name: str, content: str) -> None:
        path = prompts_dir / "shared" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_shared_fragment_markers_expand_during_template_loading(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            prompts_dir = tmp_path / "prompts"

            self._write_builtin_template(
                prompts_dir,
                "agents",
                "coder",
                "Header\n[[shared:preference-memory]]\n{project_instructions}\nConstraints:\n",
            )
            self._write_shared_fragment(
                prompts_dir,
                "preference-memory",
                "Shared preference memory block.\n",
            )

            with patch.object(prompts_module, "PROMPTS_DIR", prompts_dir):
                loaded = prompts_module._load_template("agents", "coder")

            self.assertIn("Shared preference memory block.", loaded)
            self.assertNotIn("[[shared:preference-memory]]", loaded)

    def test_shared_fragment_placeholders_are_rendered_with_template_format_map(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            prompts_dir = tmp_path / "prompts"

            self._write_builtin_template(
                prompts_dir,
                "agents",
                "coder",
                "Start\n[[shared:preference-memory]]\n{project_instructions}\nConstraints:\n",
            )
            self._write_shared_fragment(
                prompts_dir,
                "preference-memory",
                "Role: {role_name}\n",
            )

            with patch.object(prompts_module, "PROMPTS_DIR", prompts_dir):
                loaded = prompts_module._load_template("agents", "coder").format_map({"role_name": "coder"})

            self.assertIn("Role: coder", loaded)

    def test_shared_fragments_preserve_project_instruction_curly_brace_safety(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            prompts_dir = tmp_path / "prompts"
            project_dir = tmp_path / "project"
            project_dir.mkdir()

            self._write_builtin_template(
                prompts_dir,
                "agents",
                "coder",
                "Start\n[[shared:preference-memory]]\n{project_instructions}\nConstraints:\n",
            )
            self._write_shared_fragment(
                prompts_dir,
                "preference-memory",
                "Shared: {shared_value}\n",
            )
            self._write_project_prompt(
                project_dir,
                "agents",
                "coder",
                "Project braces stay literal: {do_not_expand}\n",
            )

            with patch.object(prompts_module, "PROMPTS_DIR", prompts_dir):
                loaded = prompts_module._load_template(
                    "agents",
                    "coder",
                    project_dir=project_dir,
                ).format_map({"shared_value": "ok"})

            self.assertIn("Shared: ok", loaded)
            self.assertIn("Project braces stay literal: {do_not_expand}", loaded)

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
            files.planning_dir.mkdir(parents=True, exist_ok=True)
            (files.planning_dir / "plan_meta.json").write_text(
                '{"needs_design": false, "needs_docs": true, "doc_files": ["docs/prompts.md"]}',
                encoding="utf-8",
            )

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
                "agentmux.workflow.prompts.subprocess.run",
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

    def test_docs_prompt_targets_architect_declared_doc_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "docs prompt", "session")
            files.planning_dir.mkdir(parents=True, exist_ok=True)
            (files.planning_dir / "plan_meta.json").write_text(
                '{"needs_design": false, "needs_docs": true, "doc_files": ["docs/file-protocol.md", "docs/prompts.md"]}',
                encoding="utf-8",
            )

            prompt = build_docs_prompt(files)

            self.assertIn(f"- {project_dir}/docs/file-protocol.md", prompt)
            self.assertIn(f"- {project_dir}/docs/prompts.md", prompt)
            self.assertNotIn(f"- {project_dir}/README.md", prompt)
            self.assertNotIn(f"- {project_dir}/CLAUDE.md", prompt)

    def test_docs_prompt_fails_when_plan_meta_lacks_doc_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "docs prompt", "session")
            files.planning_dir.mkdir(parents=True, exist_ok=True)
            (files.planning_dir / "plan_meta.json").write_text(
                '{"needs_design": false, "needs_docs": true}',
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                build_docs_prompt(files)

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

    def test_preference_capture_prompts_render_project_and_proposal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "preference capture", "session")

            product_prompt = build_product_manager_prompt(files)
            architect_prompt = build_architect_prompt(files)
            reviewer_prompt = build_reviewer_prompt(files)

            with patch(
                "agentmux.workflow.prompts.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ):
                confirmation_prompt = build_confirmation_prompt(files)

            self.assertIn(str(project_dir), product_prompt)
            self.assertIn(str(project_dir), architect_prompt)
            self.assertIn(str(project_dir), reviewer_prompt)
            self.assertIn(str(project_dir), confirmation_prompt)

            self.assertIn(files.relative_path(files.pm_preference_proposal), product_prompt)
            self.assertIn(files.relative_path(files.architect_preference_proposal), architect_prompt)
            self.assertIn(files.relative_path(files.reviewer_preference_proposal), reviewer_prompt)
            self.assertIn(files.relative_path(files.reviewer_preference_proposal), confirmation_prompt)

    def test_agent_preference_prompts_include_shared_block_and_role_specific_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "preference capture", "session")

            product_prompt = build_product_manager_prompt(files)
            architect_prompt = build_architect_prompt(files)
            reviewer_prompt = build_reviewer_prompt(files)

            shared_line = "Exclude one-time feedback specific to this feature (single bug fixes, typos, or scope-only corrections)."
            self.assertIn(shared_line, product_prompt)
            self.assertIn(shared_line, architect_prompt)
            self.assertIn(shared_line, reviewer_prompt)

            self.assertIn('"source_role":"product-manager"', product_prompt)
            self.assertIn(files.relative_path(files.pm_preference_proposal), product_prompt)

            self.assertIn('"source_role":"architect"', architect_prompt)
            self.assertIn(files.relative_path(files.architect_preference_proposal), architect_prompt)

            self.assertIn("Implementation review (`06_review/review.md`): focus strictly on correctness", reviewer_prompt)
            self.assertIn("Persist approved candidates only via", reviewer_prompt)
            self.assertIn(files.relative_path(files.reviewer_preference_proposal), reviewer_prompt)

    def test_affected_prompt_templates_use_shared_preference_fragment(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        template_paths = [
            repo_root / "agentmux/prompts/agents/product-manager.md",
            repo_root / "agentmux/prompts/agents/architect.md",
            repo_root / "agentmux/prompts/agents/reviewer.md",
            repo_root / "agentmux/prompts/commands/confirmation.md",
        ]

        for template_path in template_paths:
            with self.subTest(template=str(template_path)):
                template = template_path.read_text(encoding="utf-8")
                self.assertIn("[[shared:preference-memory]]", template)

    def test_cross_prompt_preference_guidance_and_proposal_paths_remain_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "cross-prompt regression", "session")
            status_output = " M agentmux/workflow/prompts.py\n?? tests/test_project_prompt_extensions_requirements.py\n"

            product_prompt = build_product_manager_prompt(files)
            architect_prompt = build_architect_prompt(files)
            reviewer_prompt = build_reviewer_prompt(files)
            with patch(
                "agentmux.workflow.prompts.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=status_output,
                    stderr="",
                ),
            ):
                confirmation_prompt = build_confirmation_prompt(files)

            rendered_prompts = {
                "product-manager": product_prompt,
                "architect": architect_prompt,
                "reviewer": reviewer_prompt,
                "confirmation": confirmation_prompt,
            }
            for prompt_name, prompt in rendered_prompts.items():
                with self.subTest(prompt=prompt_name):
                    self.assertIn("approve, edit, or dismiss each candidate", prompt.lower())
                    self.assertIn("do not persist anything without explicit user approval", prompt.lower())

            self.assertIn(files.relative_path(files.pm_preference_proposal), product_prompt)
            self.assertIn(files.relative_path(files.architect_preference_proposal), architect_prompt)
            self.assertIn(files.relative_path(files.reviewer_preference_proposal), reviewer_prompt)
            self.assertIn(files.relative_path(files.reviewer_preference_proposal), confirmation_prompt)
            self.assertIn(status_output.strip(), confirmation_prompt)

    def test_confirmation_prompt_includes_preference_persistence_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "preference capture", "session")

            with patch(
                "agentmux.workflow.prompts.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ):
                prompt = build_confirmation_prompt(files)

            self.assertIn("approve, edit, or dismiss each candidate", prompt.lower())
            self.assertIn(".agentmux/prompts/agents/<role>.md", prompt)
            self.assertIn("do not persist anything without explicit user approval", prompt.lower())

    def test_confirmation_template_uses_shared_preference_memory_fragment(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        template_path = repo_root / "agentmux/prompts/commands/confirmation.md"
        template = template_path.read_text(encoding="utf-8")

        self.assertIn("[[shared:preference-memory]]", template)

    def test_confirmation_prompt_preserves_confirmation_only_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp_path = Path(td)
            project_dir = tmp_path / "project"
            feature_dir = tmp_path / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "confirmation guidance", "session")
            status_output = " M agentmux/workflow/prompts.py\n?? tests/test_project_prompt_extensions_requirements.py\n"

            with patch(
                "agentmux.workflow.prompts.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "status", "--porcelain"],
                    returncode=0,
                    stdout=status_output,
                    stderr="",
                ),
            ):
                prompt = build_confirmation_prompt(files)

            self.assertIn(status_output.strip(), prompt)
            self.assertIn('{"action": "approve", "commit_message": "...", "exclude_files": ["relative/path"]}', prompt)
            self.assertIn("exclude_files` is optional and defaults to `[]`", prompt)
            self.assertIn("Ask for exclusions only. Do not ask the user to enumerate all commit files.", prompt)
            self.assertIn("Approved proposals are later applied by the orchestrator", prompt)
            self.assertIn("If no candidates are approved, do not write the proposal artifact.", prompt)
            self.assertIn("Do not revise `02_planning/plan.md` in this step.", prompt)
            self.assertIn("Do not update `state.json` from the confirmation step.", prompt)


if __name__ == "__main__":
    unittest.main()
