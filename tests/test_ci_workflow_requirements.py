from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class CIWorkflowRequirementsTests(unittest.TestCase):
    def test_requirements_dev_include_pytest_dependency(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        requirements_dev = (repo_root / "requirements-dev.txt").read_text(
            encoding="utf-8"
        )
        # Check for pytest in dev requirements (either pinned == or minimum >=)
        self.assertTrue(
            "pytest==" in requirements_dev or "pytest>=" in requirements_dev,
            "pytest dependency not found in requirements-dev.txt",
        )

    def test_github_actions_workflow_runs_tests_on_push_and_pull_requests(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        workflow_path = repo_root / ".github" / "workflows" / "ci.yml"
        self.assertTrue(
            workflow_path.exists(), "Workflow file .github/workflows/ci.yml must exist"
        )

        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        self.assertEqual("test", workflow.get("name"))
        triggers = workflow.get("on", workflow.get(True))
        self.assertIsNotNone(triggers)
        self.assertIn("push", triggers)
        self.assertIn("pull_request", triggers)

        jobs = workflow["jobs"]
        self.assertIn("test", jobs)
        steps = jobs["test"]["steps"]

        self.assertTrue(
            any(step.get("uses") == "actions/checkout@v4" for step in steps)
        )
        self.assertTrue(
            any(step.get("uses") == "actions/setup-python@v5" for step in steps)
        )
        self.assertTrue(
            any(
                step.get("uses") == "actions/setup-python@v5"
                and str(step.get("with", {}).get("python-version")) == "3.10"
                for step in steps
            )
        )
        # CI should install from requirements-dev.txt which includes test dependencies
        self.assertTrue(
            any(
                "python -m pip install -r requirements-dev.txt" in step.get("run", "")
                for step in steps
            )
        )
        self.assertTrue(
            any("python -m pytest tests" in step.get("run", "") for step in steps)
        )


if __name__ == "__main__":
    unittest.main()
