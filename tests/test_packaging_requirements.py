from __future__ import annotations

import unittest
from pathlib import Path


class PackagingRequirementsTests(unittest.TestCase):
    def test_pyproject_declares_agentmux_package_and_console_script(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        pyproject_path = repo_root / "pyproject.toml"
        self.assertTrue(pyproject_path.exists(), "pyproject.toml must exist at repo root")

        import tomllib

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        project = data["project"]
        self.assertEqual("agentmux", project["name"])
        self.assertIn("watchdog>=6.0.0", project["dependencies"])
        self.assertIn("PyYAML>=6.0.0", project["dependencies"])
        self.assertIn("questionary>=2.0.0", project["dependencies"])
        self.assertIn("rich>=13.0.0", project["dependencies"])
        self.assertIn("mcp>=1.0.0", project["dependencies"])

        scripts = project["scripts"]
        self.assertEqual("agentmux.pipeline:main", scripts["agentmux"])

        package_find = data["tool"]["setuptools"]["packages"]["find"]
        self.assertIn("agentmux*", package_find["include"])

        package_data = data["tool"]["setuptools"]["package-data"]["agentmux"]
        self.assertIn("prompts/**/*.md", package_data)
        self.assertIn("defaults/*.yaml", package_data)

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
