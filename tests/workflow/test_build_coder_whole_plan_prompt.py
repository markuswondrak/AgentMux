"""Tests for build_coder_whole_plan_prompt (single-coder whole-plan prompt)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from agentmux.configuration.providers import get_provider, resolve_agent
from agentmux.shared.models import SESSION_DIR_NAMES, AgentConfig, RuntimeFiles
from agentmux.workflow.prompts import build_coder_whole_plan_prompt


def _runtime_files(feature_dir: Path) -> RuntimeFiles:
    return RuntimeFiles(
        project_dir=feature_dir.parent,
        feature_dir=feature_dir,
        product_management_dir=feature_dir / SESSION_DIR_NAMES["product_management"],
        architecting_dir=feature_dir / SESSION_DIR_NAMES["architecting"],
        planning_dir=feature_dir / SESSION_DIR_NAMES["planning"],
        research_dir=feature_dir / SESSION_DIR_NAMES["research"],
        design_dir=feature_dir / SESSION_DIR_NAMES["design"],
        implementation_dir=feature_dir / SESSION_DIR_NAMES["implementation"],
        review_dir=feature_dir / SESSION_DIR_NAMES["review"],
        completion_dir=feature_dir / SESSION_DIR_NAMES["completion"],
        context=feature_dir / "context.md",
        requirements=feature_dir / "requirements.md",
        plan=feature_dir / SESSION_DIR_NAMES["planning"] / "plan.md",
        architecture=feature_dir
        / SESSION_DIR_NAMES["architecting"]
        / "architecture.md",
        tasks=feature_dir / SESSION_DIR_NAMES["planning"] / "tasks.md",
        execution_plan=feature_dir
        / SESSION_DIR_NAMES["planning"]
        / "execution_plan.yaml",
        design=feature_dir / SESSION_DIR_NAMES["design"] / "design.md",
        review=feature_dir / SESSION_DIR_NAMES["review"] / "review.md",
        fix_request=feature_dir / SESSION_DIR_NAMES["review"] / "fix_request.md",
        changes=feature_dir / SESSION_DIR_NAMES["completion"] / "changes.md",
        summary=feature_dir / SESSION_DIR_NAMES["completion"] / "summary.md",
        state=feature_dir / "state.json",
        runtime_state=feature_dir / "runtime_state.json",
        orchestrator_log=feature_dir / "orchestrator.log",
        created_files_log=feature_dir / "created_files.log",
        status_log=feature_dir / "status_log.txt",
    )


class BuildCoderWholePlanPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.feature_dir = Path(self._td.name) / "feature"
        self.feature_dir.mkdir(parents=True)
        planning = self.feature_dir / SESSION_DIR_NAMES["planning"]
        planning.mkdir(parents=True)
        (planning / "execution_plan.yaml").write_text(
            yaml.dump(
                {
                    "groups": [
                        {
                            "group_id": "g1",
                            "mode": "serial",
                            "plans": [{"file": "plan_1.md", "name": "P1"}],
                        }
                    ],
                },
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        (planning / "plan_1.md").write_text("scope", encoding="utf-8")
        (planning / "tasks_1.md").write_text("- [ ] task", encoding="utf-8")
        (self.feature_dir / "context.md").write_text("# ctx\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_without_agent_uses_sequential_sub_agent_instruction(self) -> None:
        files = _runtime_files(self.feature_dir)
        text = build_coder_whole_plan_prompt(files)
        self.assertIn("Only move to the next plan once", text)

    def test_with_sub_agent_tool_uses_parallel_instruction_and_tool_name(self) -> None:
        files = _runtime_files(self.feature_dir)
        agent = AgentConfig(
            role="coder",
            cli="claude",
            model="sonnet",
            sub_agent_tool="mcp__example__spawn_lane",
        )
        text = build_coder_whole_plan_prompt(files, agent=agent)
        self.assertNotIn("Only move to the next plan once", text)
        self.assertIn("/mcp__example__spawn_lane", text)
        self.assertIn("parallel", text.lower())

    def test_with_agent_without_sub_agent_tool_keeps_sequential(self) -> None:
        files = _runtime_files(self.feature_dir)
        agent = AgentConfig(role="coder", cli="claude", model="sonnet")
        text = build_coder_whole_plan_prompt(files, agent=agent)
        self.assertIn("Only move to the next plan once", text)

    def test_copilot_resolve_agent_whole_plan_prompt_uses_parallel_task_instruction(
        self,
    ) -> None:
        """Builtin copilot: sub_agent_tool=task resolves to parallel item 14."""
        files = _runtime_files(self.feature_dir)
        copilot = get_provider("copilot")
        agent = resolve_agent(copilot, "coder", {})
        self.assertEqual(agent.sub_agent_tool, "task")
        text = build_coder_whole_plan_prompt(files, agent=agent)
        self.assertNotIn("Only move to the next plan once", text)
        self.assertIn("/task", text)
        self.assertIn("parallel", text.lower())

    def test_claude_resolve_agent_whole_plan_prompt_stays_sequential(self) -> None:
        files = _runtime_files(self.feature_dir)
        claude = get_provider("claude")
        agent = resolve_agent(claude, "coder", {})
        self.assertIsNone(agent.sub_agent_tool)
        text = build_coder_whole_plan_prompt(files, agent=agent)
        self.assertIn("Only move to the next plan once", text)
