from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import agentmux.pipeline.application as application
import agentmux.pipeline as pipeline
from agentmux.terminal_ui.console import ConsoleUI
from agentmux.configuration import load_layered_config
from agentmux.integrations.github import (
    GitHubBootstrapper,
    assemble_pr_body,
    check_gh_authenticated,
    check_gh_available,
    create_branch_and_pr,
    extract_issue_number,
    fetch_issue,
)
from agentmux.shared.models import AgentConfig, GitHubConfig


class GitHubConfigResolutionTests(unittest.TestCase):
    def test_load_layered_config_includes_github_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                loaded = load_layered_config(project_dir)

            self.assertEqual("main", loaded.github.base_branch)
            self.assertTrue(loaded.github.draft)
            self.assertEqual("feature/", loaded.github.branch_prefix)

    def test_project_config_can_override_github_settings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            project_dir.mkdir()
            project_cfg = project_dir / ".agentmux"
            project_cfg.mkdir()
            (project_cfg / "config.yaml").write_text(
                """
github:
  base_branch: develop
  draft: false
  branch_prefix: feat/
""".strip()
                + "\n",
                encoding="utf-8",
            )

            with patch("agentmux.configuration.USER_CONFIG_PATH", Path(td) / "missing-user-config.yaml"):
                loaded = load_layered_config(project_dir)

            self.assertEqual("develop", loaded.github.base_branch)
            self.assertFalse(loaded.github.draft)
            self.assertEqual("feat/", loaded.github.branch_prefix)


class GitHubHelpersTests(unittest.TestCase):
    def test_extract_issue_number_accepts_plain_number(self) -> None:
        self.assertEqual("42", extract_issue_number("42"))

    def test_extract_issue_number_accepts_github_issue_url(self) -> None:
        self.assertEqual("314", extract_issue_number("https://github.com/acme/demo/issues/314"))

    def test_extract_issue_number_rejects_non_numeric(self) -> None:
        with self.assertRaises(ValueError):
            extract_issue_number("not-an-issue")

    def test_check_gh_available_and_authenticated_return_false_when_binary_missing(self) -> None:
        with patch("agentmux.integrations.github.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(check_gh_available())
            self.assertFalse(check_gh_authenticated())

    def test_fetch_issue_returns_title_and_body(self) -> None:
        with patch(
            "agentmux.integrations.github.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["gh", "issue", "view", "42", "--json", "title,body"],
                returncode=0,
                stdout=json.dumps({"title": "Fix auth", "body": "Issue details"}),
                stderr="",
            ),
        ) as run_mock:
            issue = fetch_issue("42")

        self.assertEqual({"title": "Fix auth", "body": "Issue details"}, issue)
        run_mock.assert_called_once_with(
            ["gh", "issue", "view", "42", "--json", "title,body"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_fetch_issue_raises_actionable_error_on_failure(self) -> None:
        with patch(
            "agentmux.integrations.github.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                returncode=1,
                cmd=["gh", "issue", "view", "42", "--json", "title,body"],
                stderr="not found",
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                fetch_issue("42")

        self.assertIn("Failed to fetch GitHub issue", str(ctx.exception))

    def test_assemble_pr_body_includes_summaries_and_closes_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / "02_planning").mkdir(parents=True)
            (feature_dir / "06_review").mkdir(parents=True)
            (feature_dir / "requirements.md").write_text(
                """
# Requirements

## Initial Request

Implement GitHub integration.
""".strip()
                + "\n",
                encoding="utf-8",
            )
            (feature_dir / "02_planning" / "plan.md").write_text(
                """
# Plan

## Scope

Create branch and open draft PR.
""".strip()
                + "\n",
                encoding="utf-8",
            )
            (feature_dir / "06_review" / "review.md").write_text(
                "Verdict: pass\nNo blocking issues.\n", encoding="utf-8"
            )

            body = assemble_pr_body(feature_dir, "42")

            self.assertIn("Implement GitHub integration.", body)
            self.assertIn("Create branch and open draft PR.", body)
            self.assertIn("Verdict: pass", body)
            self.assertIn("Closes #42", body)

    def test_assemble_pr_body_reads_phase_numbered_plan_and_review_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            (feature_dir / "02_planning").mkdir(parents=True)
            (feature_dir / "06_review").mkdir(parents=True)
            (feature_dir / "requirements.md").write_text(
                """
# Requirements

## Initial Request

Wire completion finalization to skip reviewer confirmation mode.
""".strip()
                + "\n",
                encoding="utf-8",
            )
            (feature_dir / "02_planning" / "plan.md").write_text(
                """
# Plan

## Scope

Finalize directly from completing when skip mode is enabled.
""".strip()
                + "\n",
                encoding="utf-8",
            )
            (feature_dir / "06_review" / "review.md").write_text(
                "Verdict: pass\nBehavior validated.\n", encoding="utf-8"
            )

            body = assemble_pr_body(feature_dir, "54")

            self.assertIn("Wire completion finalization", body)
            self.assertIn("Finalize directly from completing", body)
            self.assertIn("Verdict: pass", body)
            self.assertIn("Closes #54", body)

    def test_create_branch_and_pr_returns_none_on_push_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td) / "project"
            feature_dir = Path(td) / "feature"
            project_dir.mkdir()
            feature_dir.mkdir()
            (feature_dir / "requirements.md").write_text("# Requirements\n", encoding="utf-8")
            (feature_dir / "02_planning").mkdir(parents=True)
            (feature_dir / "02_planning" / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (feature_dir / "06_review").mkdir(parents=True)
            (feature_dir / "06_review" / "review.md").write_text("Verdict: pass\n", encoding="utf-8")

            with patch(
                "agentmux.integrations.github.subprocess.run",
                side_effect=[
                    subprocess.CompletedProcess(args=["git", "checkout"], returncode=0, stdout="", stderr=""),
                    subprocess.CalledProcessError(returncode=1, cmd=["git", "push"], stderr="rejected"),
                ],
            ):
                result = create_branch_and_pr(
                    project_dir=project_dir,
                    feature_slug="demo",
                    github_config=GitHubConfig(),
                    issue_number=None,
                    feature_dir=feature_dir,
                )

        self.assertIsNone(result)


class PipelineIssueTriggerTests(unittest.TestCase):
    def _loaded_config(self) -> SimpleNamespace:
        return SimpleNamespace(
            session_name="session-x",
            max_review_iterations=3,
            github=GitHubConfig(),
            agents={
                "architect": AgentConfig(role="architect", cli="claude", model="opus", args=[]),
            },
        )

    def test_parse_args_accepts_issue_flag(self) -> None:
        with patch("sys.argv", ["pipeline.py", "ship feature", "--issue", "42"]):
            args = pipeline.parse_args()
        self.assertEqual("42", args.issue)

    def test_main_fails_fast_when_issue_used_and_gh_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir)
            args = argparse.Namespace(
                prompt="ignored",
                name=None,
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=None,
                resume=None,
                issue="42",
            )

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=self._loaded_config()
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), self.assertRaises(SystemExit) as ctx:
                app.run(args)

        self.assertIn("gh CLI is required for --issue", str(ctx.exception))

    def test_main_bootstraps_prompt_and_state_from_issue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=lambda _message: None))
            args = argparse.Namespace(
                prompt="local prompt",
                name=None,
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=None,
                resume=None,
                issue="https://github.com/acme/demo/issues/42",
            )

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=self._loaded_config()
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                return_value=self._loaded_config().agents,
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=True
            ), patch(
                "agentmux.integrations.github.check_gh_authenticated", return_value=True
            ), patch(
                "agentmux.integrations.github.fetch_issue",
                return_value={"title": "Fix API auth flow", "body": "Issue-sourced requirements"},
            ), patch(
                "agentmux.sessions.datetime"
            ) as datetime_mock, patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch(
                "agentmux.pipeline.application.PipelineApplication._start_background_orchestrator", return_value=None
            ), patch(
                "agentmux.pipeline.application.subprocess.run", return_value=None
            ):
                datetime_mock.now.return_value.strftime.return_value = "20260322-203228"
                result = app.run(args)

            self.assertEqual(0, result)
            feature_dir = project_dir / ".agentmux" / ".sessions" / "20260322-203228-fix-api-auth-flow"
            self.assertTrue(feature_dir.exists())
            req_text = (feature_dir / "requirements.md").read_text(encoding="utf-8")
            self.assertIn("Issue-sourced requirements", req_text)
            self.assertNotIn("local prompt", req_text)

            state = json.loads((feature_dir / "state.json").read_text(encoding="utf-8"))
            self.assertTrue(state["gh_available"])
            self.assertEqual("42", state["issue_number"])

    def test_main_without_issue_warns_and_sets_gh_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            messages: list[str] = []
            app = application.PipelineApplication(project_dir, ui=ConsoleUI(output_fn=messages.append))
            args = argparse.Namespace(
                prompt="normal run",
                name="demo",
                config=None,
                keep_session=False,
                product_manager=False,
                orchestrate=None,
                resume=None,
                issue=None,
            )

            with patch.object(app, "ensure_dependencies", return_value=None), patch(
                "agentmux.pipeline.application.load_layered_config", return_value=self._loaded_config()
            ), patch(
                "agentmux.pipeline.application.tmux_session_exists", return_value=False
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.ensure_project_config", return_value=None
            ), patch(
                "agentmux.pipeline.application.McpAgentPreparer.prepare_feature_agents",
                return_value=self._loaded_config().agents,
            ), patch(
                "agentmux.integrations.github.check_gh_available", return_value=False
            ), patch(
                "agentmux.pipeline.application.TmuxRuntimeFactory.create", return_value=object()
            ), patch(
                "agentmux.pipeline.application.PipelineApplication._start_background_orchestrator", return_value=None
            ), patch(
                "agentmux.pipeline.application.subprocess.run", return_value=None
            ):
                result = app.run(args)

            self.assertEqual(0, result)
            state = json.loads(
                (project_dir / ".agentmux" / ".sessions" / "demo" / "state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(state["gh_available"])
            printed = "\n".join(messages)
            self.assertIn("gh CLI not available", printed)


class GitHubBootstrapperTests(unittest.TestCase):
    def test_detect_pr_availability_warns_when_tools_unavailable(self) -> None:
        messages: list[str] = []
        bootstrapper = GitHubBootstrapper(Path("/tmp/project"), GitHubConfig(), output=messages.append)

        with patch("agentmux.integrations.github.check_gh_available", return_value=False):
            available = bootstrapper.detect_pr_availability()

        self.assertFalse(available)
        self.assertIn("gh CLI not available", "\n".join(messages))


if __name__ == "__main__":
    unittest.main()
