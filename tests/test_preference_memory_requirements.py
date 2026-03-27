from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentmux.shared.models import PreferenceProposal
from agentmux.sessions.state_store import create_feature_files
from agentmux.workflow.preference_memory import (
    apply_preference_proposal,
    load_preference_proposal,
    normalize_preference_bullet,
    proposal_artifact_for_source,
)


class PreferenceMemoryRequirementsTests(unittest.TestCase):
    def test_preference_proposal_parses_valid_payload(self) -> None:
        payload = {
            "source_role": "reviewer",
            "approved": [
                {"target_role": "coder", "bullet": "- Prefer focused test cases"},
                {"target_role": "architect", "bullet": "Prefer explicit tradeoff notes"},
            ],
        }

        proposal = PreferenceProposal.from_dict(payload)

        self.assertEqual("reviewer", proposal.source_role)
        self.assertEqual(2, len(proposal.approved))
        self.assertEqual("coder", proposal.approved[0].target_role)
        self.assertEqual("- Prefer focused test cases", proposal.approved[0].bullet)

    def test_preference_proposal_rejects_invalid_payloads(self) -> None:
        with self.assertRaises(ValueError):
            PreferenceProposal.from_dict({"source_role": "reviewer"})

        with self.assertRaises(ValueError):
            PreferenceProposal.from_dict(
                {
                    "source_role": "reviewer",
                    "approved": [{"target_role": "coder", "bullet": ""}],
                }
            )

        with self.assertRaises(ValueError):
            PreferenceProposal.from_dict(
                {
                    "source_role": "unknown",
                    "approved": [{"target_role": "coder", "bullet": "- Keep tests small"}],
                }
            )

    def test_load_preference_proposal_parses_json_file_and_missing_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proposal_path = Path(td) / "proposal.json"

            self.assertIsNone(load_preference_proposal(proposal_path))

            proposal_path.write_text(
                json.dumps(
                    {
                        "source_role": "architect",
                        "approved": [{"target_role": "reviewer", "bullet": "- Call out regressions first"}],
                    }
                ),
                encoding="utf-8",
            )

            proposal = load_preference_proposal(proposal_path)

            assert proposal is not None
            self.assertEqual("architect", proposal.source_role)
            self.assertEqual("reviewer", proposal.approved[0].target_role)

    def test_normalization_handles_whitespace_bullets_and_case(self) -> None:
        left = normalize_preference_bullet("  -   Prefer   Pytest   fixtures ")
        right = normalize_preference_bullet("* prefer pytest fixtures")

        self.assertEqual(left, right)

    def test_source_role_maps_to_expected_session_proposal_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            project_dir = tmp / "project"
            feature_dir = tmp / "feature"
            project_dir.mkdir()
            files = create_feature_files(project_dir, feature_dir, "preferences", "session-x")

            self.assertEqual(files.pm_preference_proposal, proposal_artifact_for_source(files, "product-manager"))
            self.assertEqual(files.architect_preference_proposal, proposal_artifact_for_source(files, "architect"))
            self.assertEqual(files.reviewer_preference_proposal, proposal_artifact_for_source(files, "reviewer"))

    def test_apply_preference_proposal_appends_only_missing_bullets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            coder_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "coder.md"
            coder_prompt.parent.mkdir(parents=True, exist_ok=True)
            coder_prompt.write_text(
                "\n".join(
                    [
                        "<!-- Project-specific instructions for the coder role. -->",
                        "- Prefer focused test cases",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            proposal = PreferenceProposal.from_dict(
                {
                    "source_role": "reviewer",
                    "approved": [
                        {"target_role": "coder", "bullet": "Prefer focused test cases"},
                        {"target_role": "coder", "bullet": " -  keep function scope tight "},
                        {"target_role": "coder", "bullet": "* Keep   function scope tight"},
                        {"target_role": "architect", "bullet": "- Keep plans executable"},
                    ],
                }
            )

            applied = apply_preference_proposal(project_dir, proposal)

            self.assertEqual(["- keep function scope tight"], applied["coder"])
            self.assertEqual(["- Keep plans executable"], applied["architect"])

            coder_text = coder_prompt.read_text(encoding="utf-8")
            self.assertIn("<!-- Project-specific instructions for the coder role. -->", coder_text)
            self.assertIn("- Prefer focused test cases", coder_text)
            self.assertIn("- keep function scope tight", coder_text)

            architect_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "architect.md"
            self.assertTrue(architect_prompt.exists())
            self.assertIn("- Keep plans executable", architect_prompt.read_text(encoding="utf-8"))

    def test_apply_preference_proposal_is_noop_when_everything_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            reviewer_prompt = project_dir / ".agentmux" / "prompts" / "agents" / "reviewer.md"
            reviewer_prompt.parent.mkdir(parents=True, exist_ok=True)
            reviewer_prompt.write_text("-   call out  regressions first\n", encoding="utf-8")
            before = reviewer_prompt.read_text(encoding="utf-8")
            proposal = PreferenceProposal.from_dict(
                {
                    "source_role": "product-manager",
                    "approved": [
                        {"target_role": "reviewer", "bullet": "- Call out regressions first"},
                        {"target_role": "reviewer", "bullet": "* call out regressions first"},
                    ],
                }
            )

            applied = apply_preference_proposal(project_dir, proposal)

            self.assertEqual({}, applied)
            self.assertEqual(before, reviewer_prompt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
