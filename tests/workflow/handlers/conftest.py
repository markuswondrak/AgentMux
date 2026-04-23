"""Shared pytest fixtures for handler unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_ctx(tmp_path: Path) -> MagicMock:
    """Create a mock PipelineContext with realistic file structure."""
    ctx = MagicMock()
    ctx.files.feature_dir = tmp_path
    ctx.files.product_management_dir = tmp_path / "01_product_management"
    ctx.files.architecting_dir = tmp_path / "02_architecting"
    ctx.files.planning_dir = tmp_path / "04_planning"
    ctx.files.design_dir = tmp_path / "05_design"
    ctx.files.implementation_dir = tmp_path / "06_implementation"
    ctx.files.review_dir = tmp_path / "07_review"
    ctx.files.completion_dir = tmp_path / "08_completion"
    ctx.files.research_dir = tmp_path / "research"
    ctx.files.changes = tmp_path / "08_completion" / "changes.md"
    ctx.files.plan = tmp_path / "04_planning" / "plan.md"
    ctx.files.tasks = tmp_path / "04_planning" / "tasks.md"
    ctx.files.design = tmp_path / "05_design" / "design.md"
    ctx.files.review = tmp_path / "07_review" / "review.md"
    ctx.files.fix_request = tmp_path / "07_review" / "fix_request.txt"
    ctx.files.requirements = tmp_path / "requirements.md"
    ctx.files.context = tmp_path / "context.md"
    ctx.files.architecture = tmp_path / "02_architecting" / "architecture.md"
    ctx.files.project_dir = tmp_path.parent
    ctx.files.relative_path = lambda p: p.relative_to(tmp_path).as_posix()
    ctx.files.state = tmp_path / "state.json"
    ctx.agents = {}
    ctx.max_review_iterations = 3
    ctx.workflow_settings.completion.skip_final_approval = False
    ctx.github_config.branch_prefix = "feature/"

    # Create required files for prompts that include them
    ctx.files.context.write_text("# Context")
    ctx.files.architecture.parent.mkdir(parents=True, exist_ok=True)
    ctx.files.architecture.write_text("# Architecture")
    (tmp_path / "requirements.md").write_text("# Requirements")
    ctx.files.plan.parent.mkdir(parents=True, exist_ok=True)
    ctx.files.plan.write_text("# Plan")

    return ctx


@pytest.fixture
def empty_state() -> dict:
    """Create an empty state dict."""
    return {}
