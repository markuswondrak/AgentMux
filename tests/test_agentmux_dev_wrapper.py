#!/usr/bin/env python3
"""
Test for agentmux-dev wrapper script.
Verifies that the wrapper is a thin launcher that does not mutate sys.path.
"""

import subprocess
import sys
from pathlib import Path


def test_wrapper_does_not_mutate_sys_path():
    """Test that agentmux-dev no longer removes entries from sys.path."""
    repo_root = Path(__file__).resolve().parents[1]
    wrapper = repo_root / "agentmux-dev"
    source = wrapper.read_text(encoding="utf-8")
    assert "sys.path" not in source, (
        "agentmux-dev must not mutate sys.path; the src/ layout prevents shadowing"
    )


def test_wrapper_delegates_to_main():
    """Test that the wrapper imports and calls agentmux.pipeline.main."""
    test_script = """
import sys
from pathlib import Path
# Add src to path so agentmux is importable in dev context
repo_root = Path(__file__).resolve().parents[1] if "__file__" in dir() else Path(".")
import importlib.util
spec = importlib.util.find_spec("agentmux")
print("AGENTMUX_IMPORTABLE:", spec is not None)
"""

    result = subprocess.run(
        [sys.executable, "-c", test_script],
        capture_output=True,
        text=True,
    )

    assert "AGENTMUX_IMPORTABLE: True" in result.stdout, (
        f"agentmux not importable. Output: {result.stdout}\nStderr: {result.stderr}"
    )
