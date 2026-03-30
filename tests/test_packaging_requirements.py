from __future__ import annotations

import unittest
from pathlib import Path


class PackagingRequirementsTests(unittest.TestCase):
    def test_root_pipeline_shim_is_removed(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        shim_path = repo_root / "pipeline.py"
        self.assertFalse(
            shim_path.exists(), "pipeline.py shim should not exist at repo root"
        )

    def test_pipeline_module_lives_inside_agentmux_package(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.assertTrue((repo_root / "agentmux" / "pipeline" / "__init__.py").exists())

    def test_requirements_include_mcp_sdk_dependency(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")
        # Check for mcp in requirements (either pinned == or minimum >=)
        self.assertTrue(
            "mcp==" in requirements or "mcp>=" in requirements,
            "mcp dependency not found in requirements.txt",
        )


if __name__ == "__main__":
    unittest.main()
