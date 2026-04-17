from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def test_debug_log_disabled_by_default() -> None:
    with tempfile.TemporaryDirectory() as td:
        feature_dir = Path(td)
        os.environ.pop("AGENTMUX_DEBUG_LOG", None)
        from agentmux.shared.debug_log import debug_log_ndjson

        debug_log_ndjson(feature_dir, message="x", data={"a": 1})
        assert not (feature_dir / "debug.log").exists()


def test_debug_log_writes_ndjson_when_enabled() -> None:
    with tempfile.TemporaryDirectory() as td:
        feature_dir = Path(td)
        os.environ["AGENTMUX_DEBUG_LOG"] = "1"
        try:
            from agentmux.shared.debug_log import debug_log_ndjson

            debug_log_ndjson(feature_dir, message="hello", data={"k": "v"})
            log_path = feature_dir / "debug.log"
            assert log_path.exists()
            text = log_path.read_text(encoding="utf-8")
            assert text.count("\n") >= 1
            assert '"message": "hello"' in text
            assert '"k": "v"' in text
        finally:
            os.environ.pop("AGENTMUX_DEBUG_LOG", None)


def test_debug_log_none_feature_dir_is_noop() -> None:
    """Passing feature_dir=None must not raise and must not create any file."""
    os.environ["AGENTMUX_DEBUG_LOG"] = "1"
    try:
        from agentmux.shared.debug_log import debug_log_ndjson

        debug_log_ndjson(None, message="should-not-log", data={})
        # No exception — the function returns silently
    finally:
        os.environ.pop("AGENTMUX_DEBUG_LOG", None)


def test_debug_log_io_error_is_silently_swallowed() -> None:
    """An I/O error during write must be silently swallowed (best-effort logging)."""
    os.environ["AGENTMUX_DEBUG_LOG"] = "1"
    try:
        from agentmux.shared.debug_log import debug_log_ndjson

        with tempfile.TemporaryDirectory() as td:
            feature_dir = Path(td)
            with patch("builtins.open", side_effect=OSError("disk full")):
                # Must not raise
                debug_log_ndjson(feature_dir, message="fail", data={"x": 1})
    finally:
        os.environ.pop("AGENTMUX_DEBUG_LOG", None)
