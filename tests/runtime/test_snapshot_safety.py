"""Tests for runtime snapshot safety under concurrent access.

Covers:
- Concurrent _persist_snapshot() calls (thread safety via Lock)
- OSError handling (exception doesn't crash the caller)
- parallel_panes cleanup via _cleanup_pane
- kill_primary clearing parallel workers
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agentmux.runtime import TmuxAgentRuntime
from agentmux.shared.models import AgentConfig


def _agents() -> dict[str, AgentConfig]:
    return {
        "architect": AgentConfig(
            role="architect",
            cli="claude",
            model="opus",
            args=[],
            trust_snippet=None,
        ),
        "coder": AgentConfig(
            role="coder",
            cli="codex",
            model="gpt-5.3-codex",
            args=[],
            trust_snippet=None,
        ),
        "code-researcher": AgentConfig(
            role="code-researcher",
            cli="claude",
            model="sonnet",
            args=[],
            trust_snippet=None,
        ),
    }


class FakeZone:
    def __init__(self, session_name: str, visible: list[str] | None = None) -> None:
        self.session_name = session_name
        self.visible = list(visible or [])
        self.shown: list[str] = []
        self.hidden: list[str] = []
        self.removed: list[str] = []

    def show(self, pane_id: str) -> None:
        self.shown.append(pane_id)
        self.visible = [pane_id]

    def hide(self, pane_id: str) -> None:
        self.hidden.append(pane_id)
        self.visible = [c for c in self.visible if c != pane_id]

    def remove(self, pane_id: str) -> None:
        self.removed.append(pane_id)
        self.visible = [c for c in self.visible if c != pane_id]


class OSErrorZone(FakeZone):
    """FakeZone that raises OSError on remove() to test error paths."""

    def __init__(
        self,
        session_name: str,
        visible: list[str] | None = None,
        fail_on: set[str] | None = None,
    ) -> None:
        super().__init__(session_name, visible)
        self.fail_on = fail_on or set()

    def remove(self, pane_id: str) -> None:
        if pane_id in self.fail_on:
            raise OSError(f"Simulated OSError for {pane_id}")
        super().remove(pane_id)


class SnapshotSafetyTests(unittest.TestCase):
    def _make_runtime(
        self, feature_dir: Path, zone: FakeZone | None = None
    ) -> TmuxAgentRuntime:
        agents = _agents()
        if zone is None:
            zone = FakeZone("test-session", ["%0"])
        return TmuxAgentRuntime(
            feature_dir=feature_dir,
            project_dir=feature_dir,
            session_name="test-session",
            agents=agents,
            primary_panes={"_control": "%0", "architect": "%1", "coder": None},
            zone=zone,
        )

    def test_concurrent_persist_snapshot_no_crash(self) -> None:
        """10 threads call _persist_snapshot simultaneously — no crash, valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            runtime = self._make_runtime(fdir)
            errors: list[Exception] = []

            def worker() -> None:
                try:
                    runtime._persist_snapshot()
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Errors during concurrent access: {errors}"
            snapshot_path = fdir / "runtime_state.json"
            assert snapshot_path.exists()
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            assert data["version"] == 2

    def test_concurrent_persist_snapshot_valid_json(self) -> None:
        """Repeated concurrent writes always produce valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            runtime = self._make_runtime(fdir)

            for _ in range(5):
                threads = [
                    threading.Thread(target=runtime._persist_snapshot) for _ in range(5)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                snapshot_path = fdir / "runtime_state.json"
                assert snapshot_path.exists()
                # Must not raise — valid JSON
                data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                assert "primary" in data
                assert "parallel" in data
                assert "version" in data

    def test_snapshot_version_field(self) -> None:
        """Version field is correctly set to SNAPSHOT_VERSION."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            runtime = self._make_runtime(fdir)
            runtime._persist_snapshot()

            data = json.loads((fdir / "runtime_state.json").read_text(encoding="utf-8"))
            assert data["version"] == 2

    def test_snapshot_process_pids(self) -> None:
        """PIDs are correctly persisted in process_pids."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            runtime = self._make_runtime(fdir)
            runtime._process_pids["%3"] = 12345
            runtime._persist_snapshot()

            data = json.loads((fdir / "runtime_state.json").read_text(encoding="utf-8"))
            assert data["process_pids"]["%3"] == 12345

    def test_snapshot_deleted_feature_dir(self) -> None:
        """Early return when feature_dir is deleted — no exception."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp) / "session"
            fdir.mkdir()
            runtime = self._make_runtime(fdir)
            runtime._persist_snapshot()  # Works
            # Delete the directory
            import shutil

            shutil.rmtree(fdir)
            # Should not raise
            runtime._persist_snapshot()

    def test_persist_snapshot_oserror_not_raised(self) -> None:
        """OSError during write is caught and logged, not raised."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            zone = FakeZone("test-session", ["%0"])

            # Patch the write to raise OSError
            original_write_text = Path.write_text

            def failing_write_text(self, *args, **kwargs):
                if str(self).endswith(".tmp"):
                    raise OSError("Simulated disk error")
                return original_write_text(self, *args, **kwargs)

            runtime = self._make_runtime(fdir, zone=zone)
            with patch.object(Path, "write_text", failing_write_text):
                # Should NOT raise
                runtime._persist_snapshot()

    def test_persist_snapshot_rename_error_not_raised(self) -> None:
        """OSError during rename is caught and logged, not raised."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            zone = FakeZone("test-session", ["%0"])

            def failing_rename(self, target):
                raise OSError("Simulated rename error")

            runtime = self._make_runtime(fdir, zone=zone)
            with patch.object(Path, "rename", failing_rename):
                # Should NOT raise
                runtime._persist_snapshot()

    def test_cleanup_pane_removes_pid_tracking(self) -> None:
        """_cleanup_pane removes the pane from _process_pids."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            zone = FakeZone("test-session", ["%0", "%3"])
            runtime = self._make_runtime(fdir, zone=zone)
            runtime._process_pids["%3"] = 99999

            runtime._cleanup_pane("%3")

            assert "%3" not in runtime._process_pids
            assert "%3" in zone.removed

    def test_finish_task_removes_worker_from_parallel(self) -> None:
        """finish_task removes the worker from parallel_panes."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            zone = FakeZone("test-session", ["%0", "%3"])
            runtime = self._make_runtime(fdir, zone=zone)
            runtime.parallel_panes["code-researcher"] = {"task-a": "%3", "task-b": "%4"}
            runtime._process_pids["%3"] = 88888

            runtime.finish_task("code-researcher", "task-a")

            assert "task-a" not in runtime.parallel_panes.get("code-researcher", {})
            assert "task-b" in runtime.parallel_panes["code-researcher"]
            assert "%3" not in runtime._process_pids

    def test_finish_last_worker_clears_role_entry(self) -> None:
        """Last worker removed → role key removed from parallel_panes."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            zone = FakeZone("test-session", ["%3"])
            runtime = self._make_runtime(fdir, zone=zone)
            runtime.parallel_panes["code-researcher"] = {"task-a": "%3"}

            runtime.finish_task("code-researcher", "task-a")

            assert "code-researcher" not in runtime.parallel_panes

    def test_kill_primary_also_clears_parallel_workers(self) -> None:
        """kill_primary clears both primary pane and parallel workers."""
        with tempfile.TemporaryDirectory() as tmp:
            fdir = Path(tmp)
            zone = FakeZone("test-session", ["%1", "%3", "%4"])
            runtime = self._make_runtime(fdir, zone=zone)
            runtime.primary_panes["coder"] = "%1"
            runtime.parallel_panes["coder"] = {"1": "%3", "2": "%4"}
            runtime._process_pids["%1"] = 11111
            runtime._process_pids["%3"] = 22222
            runtime._process_pids["%4"] = 33333

            runtime.kill_primary("coder")

            assert runtime.primary_panes["coder"] is None
            assert "coder" not in runtime.parallel_panes
            assert "%1" not in runtime._process_pids
            assert "%3" not in runtime._process_pids
            assert "%4" not in runtime._process_pids
