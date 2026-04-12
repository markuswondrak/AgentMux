from __future__ import annotations

import unittest
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "src" / "agentmux" / "prompts"

# Tool names that should exist (unprefixed) in prompt files
VALID_TOOL_NAMES = {
    "submit_architecture",
    "submit_plan",
    "submit_review",
    "submit_done",
    "submit_research_done",
    "submit_pm_done",
}

# Old prefixed names that must NOT appear in any prompt file
DEPRECATED_TOOL_NAMES = {
    "agentmux_submit_architecture",
    "agentmux_submit_execution_plan",
    "agentmux_submit_subplan",
    "agentmux_submit_plan",
    "agentmux_submit_review",
}


class PromptToolNameMigrationTests(unittest.TestCase):
    """Ensure all prompt files use unprefixed MCP tool names."""

    def _prompt_files(self) -> list[Path]:
        files: list[Path] = []
        for root in (
            PROMPTS_DIR / "agents",
            PROMPTS_DIR / "shared",
            PROMPTS_DIR / "commands",
        ):
            if root.exists():
                files.extend(root.glob("*.md"))
        return sorted(files)

    def test_no_deprecated_agentmux_prefix_in_prompt_files(self) -> None:
        """No prompt file should reference an agentmux_ prefixed tool name."""
        violations: list[str] = []
        for path in self._prompt_files():
            content = path.read_text(encoding="utf-8")
            for deprecated in DEPRECATED_TOOL_NAMES:
                if deprecated in content:
                    violations.append(
                        f"{path.relative_to(PROMPTS_DIR)}: contains '{deprecated}'"
                    )
        self.assertEqual(
            [],
            violations,
            "Deprecated tool names found in prompt files:\n" + "\n".join(violations),
        )

    def test_handoff_contract_architecture_uses_unprefixed_submit(self) -> None:
        """handoff-contract-architecture.md should reference submit_architecture."""
        path = PROMPTS_DIR / "shared" / "handoff-contract-architecture.md"
        content = path.read_text(encoding="utf-8")
        self.assertIn("submit_architecture", content)
        self.assertNotIn("agentmux_submit_architecture", content)

    def test_handoff_contract_plan_uses_unprefixed_submit(self) -> None:
        """handoff-contract-plan.md should reference unprefixed submit_plan tool."""
        path = PROMPTS_DIR / "shared" / "handoff-contract-plan.md"
        content = path.read_text(encoding="utf-8")
        self.assertIn("submit_plan", content)
        self.assertNotIn("agentmux_submit_plan", content)
        self.assertNotIn("submit_subplan", content)
        self.assertNotIn("submit_execution_plan", content)

    def test_handoff_contract_review_uses_unprefixed_submit(self) -> None:
        """handoff-contract-review.md should reference submit_review."""
        path = PROMPTS_DIR / "shared" / "handoff-contract-review.md"
        content = path.read_text(encoding="utf-8")
        self.assertIn("submit_review", content)
        self.assertNotIn("agentmux_submit_review", content)

    def test_architect_prompt_mentions_submit_research_done(self) -> None:
        """architect.md should document submit_research_done."""
        path = PROMPTS_DIR / "agents" / "architect.md"
        content = path.read_text(encoding="utf-8")
        self.assertIn("submit_research_done", content)

    def test_coder_prompt_mentions_submit_done(self) -> None:
        """coder.md should document submit_done."""
        path = PROMPTS_DIR / "agents" / "coder.md"
        content = path.read_text(encoding="utf-8")
        self.assertIn("submit_done", content)

    def test_product_manager_prompt_mentions_submit_pm_done(self) -> None:
        """product-manager.md should document submit_pm_done."""
        path = PROMPTS_DIR / "agents" / "product-manager.md"
        content = path.read_text(encoding="utf-8")
        self.assertIn("submit_pm_done", content)


if __name__ == "__main__":
    unittest.main()
