from __future__ import annotations

import unittest
from pathlib import Path


class PackagingRequirementsTests(unittest.TestCase):
    def test_root_pipeline_is_backward_compatibility_shim(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        shim_path = repo_root / "pipeline.py"
        self.assertTrue(shim_path.exists(), "pipeline.py shim must exist at repo root")

        source = shim_path.read_text(encoding="utf-8")
        self.assertIn("from agentmux.pipeline import main", source)
        self.assertIn("sys.exit(main())", source)

    def test_pipeline_module_lives_inside_agentmux_package(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        self.assertTrue((repo_root / "agentmux" / "pipeline.py").exists())

    def test_requirements_include_mcp_sdk_dependency(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("mcp>=1.0.0", requirements)


if __name__ == "__main__":
    unittest.main()
