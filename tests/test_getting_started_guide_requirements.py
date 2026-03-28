from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class GettingStartedGuideRequirementsTests(unittest.TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_getting_started_guide_covers_required_sections_and_commands(self) -> None:
        text = self._read("docs/getting-started.md")

        self.assertIn("# Getting Started", text)
        self.assertIn("## Prerequisites Checklist", text)
        self.assertIn("python3 --version", text)
        self.assertIn("tmux -V", text)
        self.assertIn("claude --version", text)
        self.assertIn("codex --version", text)
        self.assertIn("gemini --version", text)
        self.assertIn("opencode --version", text)
        self.assertIn("authenticated", text.lower())

        self.assertIn("## Installation", text)
        self.assertIn("python3 -m pip install git+https://github.com/markuswondrak/AgentMux.git", text)
        self.assertIn("pipx install git+https://github.com/markuswondrak/AgentMux.git", text)
        self.assertIn("pipx install --force git+https://github.com/markuswondrak/AgentMux.git", text)
        self.assertIn("python3 -m pip install -e .", text)
        self.assertIn("agentmux --help", text)

        self.assertIn("## Project Setup (`agentmux init`)", text)
        self.assertIn("Default provider", text)
        self.assertIn("Role setup", text)
        self.assertIn("Base branch", text)
        self.assertIn("Create draft PRs by default?", text)
        self.assertIn("Branch prefix", text)
        self.assertIn("CLAUDE.md setup", text)
        self.assertIn("Select prompt stubs to create", text)
        self.assertIn("agentmux init --defaults", text)
        self.assertIn(".agentmux/config.yaml", text)
        self.assertIn(".agentmux/prompts/agents/<role>.md", text)

        self.assertIn("## First Pipeline Run", text)
        self.assertIn('agentmux "Add a health check endpoint"', text)
        self.assertIn("tmux attach -t <session-name>", text)
        self.assertIn("planning", text.lower())
        self.assertIn("implementing", text.lower())
        self.assertIn("reviewing", text.lower())
        self.assertIn("completing", text.lower())
        self.assertIn("approve", text.lower())
        self.assertIn("pull request", text.lower())

        self.assertIn("## Tmux Essentials", text)
        self.assertIn("Ctrl-b d", text)
        self.assertIn("Ctrl-b <arrow>", text)

        self.assertIn("## Troubleshooting", text)
        self.assertIn("brew install tmux", text)
        self.assertIn("apt install tmux", text)
        self.assertIn("hangs", text.lower())

        self.assertIn("## Next Steps", text)
        self.assertIn("--product-manager", text)
        self.assertIn("--issue", text)
        self.assertIn("--resume", text)
        self.assertIn("(configuration.md)", text)
        self.assertIn("(session-resumption.md)", text)

    def test_getting_started_guide_stays_under_200_lines(self) -> None:
        lines = self._read("docs/getting-started.md").splitlines()
        self.assertLessEqual(len(lines), 200)

    def test_readme_has_quickstart_cross_link_and_docs_entry(self) -> None:
        readme = self._read("README.md")
        quickstart_block = """# Resume an interrupted run
agentmux --resume

```"""
        guide_line = "For a detailed walkthrough, see the [Getting Started guide](docs/getting-started.md)."
        gh_line = "If `gh` is authenticated, AgentMux can bootstrap from issue content and open a pull request when the pipeline completes."

        self.assertIn(quickstart_block, readme)
        self.assertIn(guide_line, readme)
        self.assertIn(gh_line, readme)
        self.assertLess(readme.index(quickstart_block), readme.index(guide_line))
        self.assertLess(readme.index(guide_line), readme.index(gh_line))

        docs_section_match = re.search(r"## Documentation\n\n(?P<section>(?:- .+\n)+)", readme)
        self.assertIsNotNone(docs_section_match)
        docs_section = docs_section_match.group("section")
        first_entry = docs_section.splitlines()[0]
        self.assertEqual(
            "- [`docs/getting-started.md`](docs/getting-started.md) — installation, setup, and first pipeline run",
            first_entry,
        )

    def test_relative_links_resolve_in_getting_started_guide(self) -> None:
        text = self._read("docs/getting-started.md")
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        relative_links = [link for link in links if not link.startswith(("http://", "https://", "#"))]

        self.assertGreater(len(relative_links), 0)
        docs_dir = REPO_ROOT / "docs"
        for link in relative_links:
            with self.subTest(link=link):
                target = (docs_dir / link).resolve()
                self.assertTrue(target.exists(), f"Missing relative link target: {link}")


if __name__ == "__main__":
    unittest.main()
