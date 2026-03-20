from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import RuntimeFiles

STATE_FILE_NAME = "state.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(state_path: Path) -> dict[str, Any]:
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def update_state(state_path: Path, status: str, updated_by: str, active_role: str | None = None) -> dict[str, Any]:
    state = load_state(state_path)
    state["status"] = status
    state["updated_at"] = now_iso()
    state["updated_by"] = updated_by
    if active_role is not None:
        state["active_role"] = active_role
    write_state(state_path, state)
    return state


def _make_runtime_files(project_dir: Path, feature_dir: Path) -> RuntimeFiles:
    return RuntimeFiles(
        project_dir=project_dir,
        feature_dir=feature_dir,
        context=feature_dir / "context.md",
        requirements=feature_dir / "requirements.md",
        plan=feature_dir / "plan.md",
        review=feature_dir / "review.md",
        fix_request=feature_dir / "fix_request.md",
        changes=feature_dir / "changes.md",
        state=feature_dir / STATE_FILE_NAME,
        orchestrator_log=feature_dir / "orchestrator.log",
    )


def create_feature_files(project_dir: Path, feature_dir: Path, prompt: str, session_name: str) -> RuntimeFiles:
    feature_dir.mkdir(parents=True, exist_ok=False)
    files = _make_runtime_files(project_dir, feature_dir)

    files.context.write_text(
        "\n".join([
            "# Context",
            "",
            "This directory is the shared handoff space for the local multi-agent pipeline MVP.",
            "",
            "## Rules",
            "",
            "- Communicate through files in this directory.",
            "- Use `state.json` for workflow transitions.",
            "- Architect owns requirements clarification, planning, and review.",
            "- Coder owns implementation in the repository root.",
            "- Keep changes aligned with `requirements.md` and `plan.md`.",
            "",
            "## Session",
            "",
            f"- tmux session: `{session_name}`",
            f"- feature directory: `{feature_dir}`",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    files.requirements.write_text(
        "\n".join([
            "# Requirements",
            "",
            "## Initial Request",
            "",
            prompt.strip(),
            "",
            "## Clarifications",
            "",
            "_Architect fills this in if clarification is needed._",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    files.plan.write_text(
        "# Plan\n\n_Architect writes the implementation plan here._\n",
        encoding="utf-8",
    )
    files.review.write_text(
        "# Review\n\n_Architect writes review findings or an explicit no-findings verdict here._\n",
        encoding="utf-8",
    )
    files.fix_request.write_text(
        "# Fix Request\n\n_Orchestrator copies review findings here when fixes are required._\n",
        encoding="utf-8",
    )

    state = {
        "feature_dir": str(feature_dir),
        "status": "architect_requested",
        "subplan_count": 0,
        "review_iteration": 0,
        "updated_at": now_iso(),
        "updated_by": "pipeline",
        "active_role": "architect",
    }
    write_state(files.state, state)
    return files


def load_runtime_files(project_dir: Path, feature_dir: Path) -> RuntimeFiles:
    return _make_runtime_files(project_dir, feature_dir)


def parse_review_verdict(review_text: str) -> str | None:
    for line in review_text.splitlines():
        normalized = line.strip().lower()
        if not normalized:
            continue
        if normalized == "verdict: pass":
            return "pass"
        if normalized == "verdict: fail":
            return "fail"
        return None
    return None


def cleanup_feature_dir(feature_dir: Path) -> None:
    try:
        shutil.rmtree(feature_dir)
        print(f"Cleaned up feature directory: {feature_dir}")
    except FileNotFoundError:
        print(f"Feature directory already removed: {feature_dir}")
    except OSError as exc:
        print(f"Failed to clean up feature directory {feature_dir}: {exc}")
