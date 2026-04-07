"""Tests for handoff contract definitions, validation, and prompt rendering."""

from __future__ import annotations

import unittest

import yaml

from agentmux.workflow.handoff_contracts import (
    ARCHITECTURE_CONTRACT,
    CONTRACTS,
    EXECUTION_PLAN_CONTRACT,
    REVIEW_CONTRACT,
    SUBPLAN_CONTRACT,
    ValidationError,
    render_contract_prompt,
    validate_submission,
)


class TestContractRegistry(unittest.TestCase):
    def test_all_contracts_registered(self):
        self.assertIn("architecture", CONTRACTS)
        self.assertIn("execution_plan", CONTRACTS)
        self.assertIn("subplan", CONTRACTS)
        self.assertIn("review", CONTRACTS)
        self.assertEqual(len(CONTRACTS), 4)

    def test_contract_field_names(self):
        self.assertIn("solution_overview", ARCHITECTURE_CONTRACT.field_names())
        self.assertIn("groups", EXECUTION_PLAN_CONTRACT.field_names())
        self.assertIn("index", SUBPLAN_CONTRACT.field_names())
        self.assertIn("verdict", REVIEW_CONTRACT.field_names())

    def test_required_fields_subset_of_all(self):
        for contract in CONTRACTS.values():
            self.assertTrue(contract.required_fields() <= contract.field_names())


class TestValidateArchitecture(unittest.TestCase):
    def _valid_data(self):
        return {
            "solution_overview": "High-level approach",
            "components": [
                {
                    "name": "AuthService",
                    "responsibility": "Auth",
                    "interfaces": ["login()"],
                }
            ],
            "interfaces_and_contracts": "REST API",
            "data_models": "User, Session",
            "cross_cutting_concerns": "Logging",
            "technology_choices": "Python + FastAPI",
            "risks_and_mitigations": "None identified",
        }

    def test_valid_submission(self):
        errors = validate_submission("architecture", self._valid_data())
        self.assertEqual(errors, [])

    def test_missing_required_field(self):
        data = self._valid_data()
        del data["solution_overview"]
        errors = validate_submission("architecture", data)
        self.assertTrue(any("solution_overview" in e for e in errors))

    def test_optional_field_omitted(self):
        data = self._valid_data()
        # design_handoff is optional
        self.assertNotIn("design_handoff", data)
        errors = validate_submission("architecture", data)
        self.assertEqual(errors, [])

    def test_component_missing_name(self):
        data = self._valid_data()
        data["components"] = [{"responsibility": "Auth", "interfaces": []}]
        errors = validate_submission("architecture", data)
        self.assertTrue(any("name" in e for e in errors))

    def test_component_missing_responsibility(self):
        data = self._valid_data()
        data["components"] = [{"name": "Svc", "interfaces": []}]
        errors = validate_submission("architecture", data)
        self.assertTrue(any("responsibility" in e for e in errors))

    def test_wrong_type_for_components(self):
        data = self._valid_data()
        data["components"] = "not a list"
        errors = validate_submission("architecture", data)
        self.assertTrue(any("invalid type" in e for e in errors))


class TestValidateExecutionPlan(unittest.TestCase):
    def _valid_data(self):
        return {
            "groups": [
                {
                    "group_id": "core",
                    "mode": "serial",
                    "plans": [{"file": "plan_1.md", "name": "Setup"}],
                }
            ],
            "review_strategy": {"severity": "medium", "focus": ["security"]},
            "needs_design": False,
            "needs_docs": True,
            "doc_files": ["docs/api.md"],
            "plan_overview": "This plan sets up core modules.",
        }

    def test_valid_submission(self):
        errors = validate_submission("execution_plan", self._valid_data())
        self.assertEqual(errors, [])

    def test_duplicate_group_id(self):
        data = self._valid_data()
        data["groups"].append(
            {
                "group_id": "core",
                "mode": "parallel",
                "plans": [{"file": "plan_2.md", "name": "Extra"}],
            }
        )
        errors = validate_submission("execution_plan", data)
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_invalid_mode(self):
        data = self._valid_data()
        data["groups"][0]["mode"] = "concurrent"
        errors = validate_submission("execution_plan", data)
        self.assertTrue(any("mode" in e for e in errors))

    def test_invalid_severity(self):
        data = self._valid_data()
        data["review_strategy"]["severity"] = "extreme"
        errors = validate_submission("execution_plan", data)
        self.assertTrue(any("severity" in e for e in errors))

    def test_plan_entry_missing_file(self):
        data = self._valid_data()
        data["groups"][0]["plans"] = [{"name": "Missing file"}]
        errors = validate_submission("execution_plan", data)
        self.assertTrue(any("file" in e and "name" in e for e in errors))

    def test_empty_groups_list(self):
        data = self._valid_data()
        data["groups"] = []
        errors = validate_submission("execution_plan", data)
        self.assertTrue(any("at least one" in e or "non-empty" in e for e in errors))


class TestValidateSubplan(unittest.TestCase):
    def _valid_data(self):
        return {
            "index": 1,
            "title": "Auth module",
            "scope": "User authentication",
            "owned_files": ["src/auth.py"],
            "dependencies": "None",
            "implementation_approach": "Step by step",
            "acceptance_criteria": "All tests pass",
            "tasks": ["Create module", "Write tests"],
        }

    def test_valid_submission(self):
        errors = validate_submission("subplan", self._valid_data())
        self.assertEqual(errors, [])

    def test_index_below_one(self):
        data = self._valid_data()
        data["index"] = 0
        errors = validate_submission("subplan", data)
        self.assertTrue(any("index" in e for e in errors))

    def test_empty_tasks(self):
        data = self._valid_data()
        data["tasks"] = []
        errors = validate_submission("subplan", data)
        self.assertTrue(any("tasks" in e for e in errors))

    def test_empty_owned_files(self):
        data = self._valid_data()
        data["owned_files"] = []
        errors = validate_submission("subplan", data)
        self.assertTrue(any("owned_files" in e for e in errors))

    def test_optional_isolation_rationale(self):
        data = self._valid_data()
        data["isolation_rationale"] = "No shared state"
        errors = validate_submission("subplan", data)
        self.assertEqual(errors, [])


class TestValidateReview(unittest.TestCase):
    def test_pass_verdict_valid(self):
        data = {"verdict": "pass", "summary": "All good"}
        errors = validate_submission("review", data)
        self.assertEqual(errors, [])

    def test_pass_with_commit_message(self):
        data = {
            "verdict": "pass",
            "summary": "All good",
            "commit_message": "feat: add auth",
        }
        errors = validate_submission("review", data)
        self.assertEqual(errors, [])

    def test_fail_requires_findings(self):
        data = {"verdict": "fail", "summary": "Issues found"}
        errors = validate_submission("review", data)
        self.assertTrue(any("findings" in e for e in errors))

    def test_fail_with_valid_findings(self):
        data = {
            "verdict": "fail",
            "summary": "Issues found",
            "findings": [
                {
                    "location": "src/auth.py:42",
                    "issue": "Missing validation",
                    "severity": "high",
                    "recommendation": "Add check",
                }
            ],
        }
        errors = validate_submission("review", data)
        self.assertEqual(errors, [])

    def test_fail_finding_missing_issue(self):
        data = {
            "verdict": "fail",
            "summary": "Issues",
            "findings": [{"recommendation": "Fix it"}],
        }
        errors = validate_submission("review", data)
        self.assertTrue(any("issue" in e for e in errors))

    def test_fail_finding_missing_recommendation(self):
        data = {
            "verdict": "fail",
            "summary": "Issues",
            "findings": [{"issue": "Bug"}],
        }
        errors = validate_submission("review", data)
        self.assertTrue(any("recommendation" in e for e in errors))

    def test_invalid_verdict(self):
        data = {"verdict": "maybe", "summary": "Unsure"}
        errors = validate_submission("review", data)
        self.assertTrue(any("verdict" in e for e in errors))


class TestValidationError(unittest.TestCase):
    def test_error_attributes(self):
        err = ValidationError("review", ["bad field", "missing thing"])
        self.assertEqual(err.contract_name, "review")
        self.assertEqual(len(err.errors), 2)
        self.assertIn("review", str(err))


class TestUnknownContract(unittest.TestCase):
    def test_unknown_contract_name(self):
        errors = validate_submission("nonexistent", {"x": 1})
        self.assertEqual(errors, ["Unknown contract: nonexistent"])


class TestRenderContractPrompt(unittest.TestCase):
    @staticmethod
    def _extract_yaml_block(text: str) -> str:
        start = text.index("```yaml") + len("```yaml")
        end = text.index("```", start)
        return text[start:end].strip()

    def test_renders_all_contracts(self):
        for name in CONTRACTS:
            text = render_contract_prompt(name)
            self.assertIn("```yaml", text)
            self.assertIn("```", text)

    def test_unknown_contract_returns_comment(self):
        text = render_contract_prompt("nonexistent")
        self.assertIn("unknown contract", text)

    def test_architecture_prompt_has_key_fields(self):
        text = render_contract_prompt("architecture")
        self.assertIn("solution_overview", text)
        self.assertIn("components", text)

    def test_optional_fields_marked(self):
        text = render_contract_prompt("architecture")
        self.assertIn("# optional", text)

    def test_review_prompt_has_verdict(self):
        text = render_contract_prompt("review")
        self.assertIn("verdict", text)

    def test_architecture_prompt_examples_parse_with_component_structure(self):
        text = render_contract_prompt("architecture")
        parsed = yaml.safe_load(self._extract_yaml_block(text))

        self.assertEqual(parsed["components"][0]["name"], "AuthService")
        self.assertEqual(
            parsed["components"][0]["responsibility"],
            "Handles user authentication",
        )

    def test_subplan_prompt_examples_parse_list_values(self):
        text = render_contract_prompt("subplan")
        parsed = yaml.safe_load(self._extract_yaml_block(text))

        self.assertEqual(
            parsed["tasks"],
            ["Create auth module", "Add login endpoint", "Write tests"],
        )
        self.assertEqual(parsed["owned_files"], ["src/auth.py", "tests/test_auth.py"])


if __name__ == "__main__":
    unittest.main()
