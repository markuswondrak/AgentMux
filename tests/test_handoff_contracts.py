"""Tests for handoff contract definitions, validation, and prompt rendering."""

from __future__ import annotations

import unittest

from agentmux.workflow.handoff_artifacts import generate_subplan_md
from agentmux.workflow.handoff_contracts import (
    ARCHITECTURE_CONTRACT,
    CONTRACTS,
    PLAN_CONTRACT,
    REVIEW_CONTRACT,
    ValidationError,
    render_contract_prompt,
    validate_submission,
)


class TestContractRegistry(unittest.TestCase):
    def test_all_contracts_registered(self):
        self.assertIn("architecture", CONTRACTS)
        self.assertIn("plan", CONTRACTS)
        self.assertIn("review", CONTRACTS)
        self.assertEqual(len(CONTRACTS), 3)

    def test_contract_field_names(self):
        self.assertEqual(ARCHITECTURE_CONTRACT.field_names(), frozenset())
        self.assertIn("groups", PLAN_CONTRACT.field_names())
        self.assertIn("subplans", PLAN_CONTRACT.field_names())
        self.assertIn("verdict", REVIEW_CONTRACT.field_names())

    def test_required_fields_subset_of_all(self):
        for contract in CONTRACTS.values():
            self.assertTrue(contract.required_fields() <= contract.field_names())


class TestValidateArchitecture(unittest.TestCase):
    def test_empty_data_passes(self):
        # Architecture is free-form MD — contract has no required YAML fields.
        errors = validate_submission("architecture", {})
        self.assertEqual(errors, [])

    def test_any_dict_passes(self):
        errors = validate_submission("architecture", {"anything": "goes"})
        self.assertEqual(errors, [])


class TestValidatePlan(unittest.TestCase):
    def _valid_data(self):
        return {
            "version": 2,
            "plan_overview": "Two-phase rollout",
            "review_strategy": {"severity": "medium", "focus": ["security"]},
            "needs_design": False,
            "needs_docs": True,
            "doc_files": ["docs/api.md"],
            "groups": [
                {
                    "group_id": "core",
                    "mode": "serial",
                    "plans": [{"index": 1, "name": "Setup"}],
                }
            ],
            "subplans": [
                {
                    "index": 1,
                    "title": "Auth module",
                    "scope": "User auth",
                    "owned_files": ["src/auth.py"],
                    "dependencies": "None",
                    "implementation_approach": "Step by step",
                    "acceptance_criteria": "All tests pass",
                    "tasks": ["Create module", "Write tests"],
                }
            ],
        }

    def test_valid_submission(self):
        errors = validate_submission("plan", self._valid_data())
        self.assertEqual(errors, [])

    def test_empty_doc_files_is_accepted(self):
        data = self._valid_data()
        data["doc_files"] = []
        errors = validate_submission("plan", data)
        self.assertEqual(errors, [])

    def test_empty_groups(self):
        data = self._valid_data()
        data["groups"] = []
        errors = validate_submission("plan", data)
        self.assertTrue(any("at least one" in e or "groups" in e for e in errors))

    def test_empty_subplans(self):
        data = self._valid_data()
        data["subplans"] = []
        errors = validate_submission("plan", data)
        self.assertTrue(any("subplans" in e for e in errors))

    def test_subplan_index_zero(self):
        data = self._valid_data()
        data["subplans"][0]["index"] = 0
        errors = validate_submission("plan", data)
        self.assertTrue(any("index" in e for e in errors))

    def test_subplan_empty_tasks(self):
        data = self._valid_data()
        data["subplans"][0]["tasks"] = []
        errors = validate_submission("plan", data)
        self.assertTrue(any("tasks" in e for e in errors))

    def test_subplan_empty_owned_files(self):
        data = self._valid_data()
        data["subplans"][0]["owned_files"] = []
        errors = validate_submission("plan", data)
        self.assertTrue(any("owned_files" in e for e in errors))

    def test_duplicate_subplan_index(self):
        data = self._valid_data()
        # Add a second subplan with index 2 so the group can reference it cleanly.
        data["subplans"].append(
            {
                "index": 2,
                "title": "Extra",
                "scope": "Extra",
                "owned_files": ["src/extra.py"],
                "dependencies": "None",
                "implementation_approach": "Do it",
                "acceptance_criteria": "Works",
                "tasks": ["Task A"],
            }
        )
        # Now duplicate index 1 — only the duplicate error should fire.
        dup = dict(data["subplans"][0])
        data["subplans"].append(dup)
        errors = validate_submission("plan", data)
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_duplicate_group_id(self):
        data = self._valid_data()
        data["subplans"].append(
            {
                "index": 2,
                "title": "Extra",
                "scope": "Extra",
                "owned_files": ["src/extra.py"],
                "dependencies": "None",
                "implementation_approach": "Do it",
                "acceptance_criteria": "Works",
                "tasks": ["Task A"],
            }
        )
        data["groups"].append(
            {
                "group_id": "core",
                "mode": "parallel",
                "plans": [{"index": 2, "name": "Extra"}],
            }
        )
        errors = validate_submission("plan", data)
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_invalid_mode(self):
        data = self._valid_data()
        data["groups"][0]["mode"] = "concurrent"
        errors = validate_submission("plan", data)
        self.assertTrue(any("mode" in e for e in errors))

    def test_invalid_severity(self):
        data = self._valid_data()
        data["review_strategy"]["severity"] = "extreme"
        errors = validate_submission("plan", data)
        self.assertTrue(any("severity" in e for e in errors))

    def test_missing_severity_raises(self):
        data = self._valid_data()
        data["review_strategy"] = {}
        errors = validate_submission("plan", data)
        self.assertTrue(any("severity is required" in e for e in errors))

    def test_empty_review_strategy_raises(self):
        data = self._valid_data()
        data["review_strategy"] = {"focus": ["security"]}
        errors = validate_submission("plan", data)
        self.assertTrue(any("severity is required" in e for e in errors))

    def test_group_plan_references_missing_subplan(self):
        data = self._valid_data()
        data["groups"][0]["plans"] = [{"index": 99, "name": "Ghost"}]
        errors = validate_submission("plan", data)
        self.assertTrue(any("99" in e for e in errors))

    def test_group_plan_missing_name(self):
        data = self._valid_data()
        data["groups"][0]["plans"] = [{"index": 1}]
        errors = validate_submission("plan", data)
        self.assertTrue(any("name" in e for e in errors))


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
    def test_renders_all_contracts(self):
        for name in CONTRACTS:
            text = render_contract_prompt(name)
            self.assertIsInstance(text, str)
            self.assertTrue(len(text) > 0)

    def test_unknown_contract_returns_comment(self):
        text = render_contract_prompt("nonexistent")
        self.assertIn("unknown contract", text)

    def test_review_prompt_has_verdict(self):
        text = render_contract_prompt("review")
        self.assertIn("verdict", text)

    def test_plan_prompt_has_key_fields(self):
        text = render_contract_prompt("plan")
        self.assertIn("groups", text)
        self.assertIn("subplans", text)


_SUBPLAN_BASE = {
    "title": "Auth module",
    "scope": "User auth",
    "owned_files": ["src/auth.py"],
    "implementation_approach": "Step by step",
    "acceptance_criteria": "All tests pass",
    "tasks": ["Create module"],
    "isolation_rationale": None,
}


class TestGenerateSubplanMd(unittest.TestCase):
    def test_dependencies_as_string(self):
        data = {**_SUBPLAN_BASE, "dependencies": "None"}
        result = generate_subplan_md(data)
        self.assertIn("## Dependencies", result)
        self.assertIn("None", result)

    def test_dependencies_as_list(self):
        data = {**_SUBPLAN_BASE, "dependencies": ["Sub-plan 1 (module must exist)"]}
        result = generate_subplan_md(data)
        self.assertIn("## Dependencies", result)
        self.assertIn("- Sub-plan 1 (module must exist)", result)

    def test_dependencies_as_empty_list(self):
        data = {**_SUBPLAN_BASE, "dependencies": []}
        result = generate_subplan_md(data)
        self.assertIn("## Dependencies", result)


class TestGenerateConsolidatedReviewMd(unittest.TestCase):
    """Tests for generate_consolidated_review_md()."""

    def test_empty_results_returns_pass_verdict(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        result = generate_consolidated_review_md({})
        self.assertEqual(result, "verdict: pass\n")

    def test_single_reviewer_returns_review_text_as_is(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        review_text = "verdict: pass\n\n## Summary\n\nAll good.\n"
        result = generate_consolidated_review_md(
            {"reviewer_logic": {"verdict": "pass", "review_text": review_text}}
        )
        self.assertEqual(result, review_text)

    def test_single_reviewer_with_empty_review_text_returns_pass(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        result = generate_consolidated_review_md(
            {"reviewer_logic": {"verdict": "pass", "review_text": ""}}
        )
        self.assertEqual(result, "verdict: pass\n")

    def test_multiple_reviewers_starts_with_verdict_pass(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        result = generate_consolidated_review_md(
            {
                "reviewer_logic": {"verdict": "pass", "review_text": "Logic OK"},
                "reviewer_quality": {"verdict": "pass", "review_text": "Quality OK"},
            }
        )
        self.assertTrue(result.startswith("verdict: pass"))

    def test_multiple_reviewers_includes_per_role_sections(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        result = generate_consolidated_review_md(
            {
                "reviewer_logic": {"verdict": "pass", "review_text": "Logic OK"},
                "reviewer_quality": {"verdict": "pass", "review_text": "Quality OK"},
            }
        )
        self.assertIn("### reviewer_logic", result)
        self.assertIn("Logic OK", result)
        self.assertIn("### reviewer_quality", result)
        self.assertIn("Quality OK", result)

    def test_multiple_reviewers_mentions_both_roles_in_summary(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        result = generate_consolidated_review_md(
            {
                "reviewer_logic": {"verdict": "pass", "review_text": "Logic OK"},
                "reviewer_quality": {"verdict": "pass", "review_text": "Quality OK"},
            }
        )
        self.assertIn("reviewer_logic", result)
        self.assertIn("reviewer_quality", result)

    def test_role_with_no_review_text_falls_back_to_verdict_line(self):
        from agentmux.workflow.handoff_artifacts import generate_consolidated_review_md

        result = generate_consolidated_review_md(
            {
                "reviewer_logic": {"verdict": "pass", "review_text": ""},
                "reviewer_quality": {"verdict": "pass", "review_text": "Quality OK"},
            }
        )
        self.assertIn("### reviewer_logic", result)
        self.assertIn("verdict: pass", result)


if __name__ == "__main__":
    unittest.main()
