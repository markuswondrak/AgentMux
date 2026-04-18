"""Tests for validation config, phase catalog, events, and validation pane runtime."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from agentmux.configuration import load_explicit_config, load_layered_config
from agentmux.runtime import TmuxAgentRuntime
from agentmux.shared.models import ValidationConfig, WorkflowSettings
from agentmux.shared.phase_catalog import PHASE_CATALOG
from agentmux.workflow.event_catalog import (
    EVENT_VALIDATION_FAILED,
    EVENT_VALIDATION_PASSED,
    WORKFLOW_EVENT_CATALOG,
)


class ValidationConfigTests(unittest.TestCase):
    def test_validation_config_default_empty_commands(self) -> None:
        cfg = ValidationConfig()
        self.assertEqual(cfg.commands, ())

    def test_workflow_settings_exposes_validation(self) -> None:
        ws = WorkflowSettings()
        self.assertIsInstance(ws.validation, ValidationConfig)
        self.assertEqual(ws.validation.commands, ())


class ValidationLayeredConfigTests(unittest.TestCase):
    def test_validation_commands_resolve_to_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.yaml"
            cfg_path.write_text(
                yaml.dump(
                    {
                        "version": 2,
                        "validation": {
                            "commands": ["npm run lint", "npm run test"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_explicit_config(cfg_path)
            self.assertEqual(
                loaded.workflow_settings.validation.commands,
                ("npm run lint", "npm run test"),
            )

    def test_missing_validation_uses_empty_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            (project_dir / ".agentmux").mkdir(parents=True)
            (project_dir / ".agentmux" / "config.yaml").write_text(
                "version: 2\n",
                encoding="utf-8",
            )
            loaded = load_layered_config(project_dir)
            self.assertEqual(loaded.workflow_settings.validation.commands, ())


class PhaseCatalogValidationTests(unittest.TestCase):
    def test_validating_phase_between_implementing_and_reviewing(self) -> None:
        names = [e.name for e in PHASE_CATALOG]
        impl_idx = names.index("implementing")
        val_idx = names.index("validating")
        rev_idx = names.index("reviewing")
        self.assertLess(impl_idx, val_idx)
        self.assertLess(val_idx, rev_idx)


class EventCatalogValidationTests(unittest.TestCase):
    def test_validation_events_in_catalog(self) -> None:
        self.assertIn(EVENT_VALIDATION_PASSED, WORKFLOW_EVENT_CATALOG)
        self.assertIn(EVENT_VALIDATION_FAILED, WORKFLOW_EVENT_CATALOG)


class RunValidationPaneTests(unittest.TestCase):
    def test_run_validation_pane_spawns_shows_and_does_not_register(self) -> None:
        zone = MagicMock()
        runtime = TmuxAgentRuntime(
            feature_dir=Path("/tmp/f"),
            project_dir=Path("/tmp/p"),
            session_name="s",
            agents={},
            primary_panes={"_control": "c0", "architect": "a0"},
            zone=zone,
        )
        before_primary = dict(runtime.primary_panes)
        before_parallel = dict(runtime.parallel_panes)

        with (
            patch(
                "agentmux.runtime._spawn_hidden_pane",
                return_value=("pane-val", 4242),
            ) as spawn_mock,
            patch("agentmux.runtime.TmuxAgentRuntime._persist_snapshot"),
        ):
            result = runtime.run_validation_pane("echo ok", "Validation")

        spawn_mock.assert_called_once_with(
            "s", Path("/tmp/p"), "echo ok", label="Validation"
        )
        zone.show.assert_called_once_with("pane-val")
        self.assertEqual(result, ("pane-val", 4242))
        self.assertEqual(runtime.primary_panes, before_primary)
        self.assertEqual(runtime.parallel_panes, before_parallel)


if __name__ == "__main__":
    unittest.main()
