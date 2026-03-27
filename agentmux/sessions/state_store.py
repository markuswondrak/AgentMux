from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from ..shared.models import RuntimeFiles, SESSION_DIR_NAMES

STATE_FILE_NAME = "state.json"


def feature_slug_from_dir(feature_dir: Path) -> str:
    """Return the human-readable slug from a feature directory name.

    Strips the leading ``YYYYMMDD-HHMMSS-`` timestamp prefix if present.
    """
    name = feature_dir.name.strip()
    match = re.match(r"^\d{8}-\d{6}-(.+)$", name)
    if match:
        slug = match.group(1).strip()
        if slug:
            return slug
    return name or "feature"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state(state_path: Path) -> dict[str, Any]:
    import time
    for attempt in range(5):
        text = state_path.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
        if attempt < 4:
            time.sleep(0.1)
    raise RuntimeError(f"state file is empty after retries: {state_path}")


def write_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def update_phase(
    state_path: Path,
    phase: str,
    updated_by: str,
    last_event: str | None = None,
    **extra_fields: Any,
) -> dict[str, Any]:
    state = load_state(state_path)
    state["phase"] = phase
    state["updated_at"] = now_iso()
    state["updated_by"] = updated_by
    if last_event is not None:
        state["last_event"] = last_event
    state.update(extra_fields)
    write_state(state_path, state)
    return state


def _make_runtime_files(project_dir: Path, feature_dir: Path) -> RuntimeFiles:
    product_management_dir = feature_dir / SESSION_DIR_NAMES["product_management"]
    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    research_dir = feature_dir / SESSION_DIR_NAMES["research"]
    design_dir = feature_dir / SESSION_DIR_NAMES["design"]
    implementation_dir = feature_dir / SESSION_DIR_NAMES["implementation"]
    review_dir = feature_dir / SESSION_DIR_NAMES["review"]
    completion_dir = feature_dir / SESSION_DIR_NAMES["completion"]
    return RuntimeFiles(
        project_dir=project_dir,
        feature_dir=feature_dir,
        product_management_dir=product_management_dir,
        planning_dir=planning_dir,
        research_dir=research_dir,
        design_dir=design_dir,
        implementation_dir=implementation_dir,
        review_dir=review_dir,
        completion_dir=completion_dir,
        context=feature_dir / "context.md",
        requirements=feature_dir / "requirements.md",
        plan=planning_dir / "plan.md",
        tasks=planning_dir / "tasks.md",
        execution_plan=planning_dir / "execution_plan.json",
        design=design_dir / "design.md",
        review=review_dir / "review.md",
        fix_request=review_dir / "fix_request.md",
        changes=completion_dir / "changes.md",
        pm_preference_proposal=product_management_dir / "approved_preferences.json",
        architect_preference_proposal=planning_dir / "approved_preferences.json",
        reviewer_preference_proposal=completion_dir / "approved_preferences.json",
        state=feature_dir / STATE_FILE_NAME,
        runtime_state=feature_dir / "runtime_state.json",
        orchestrator_log=feature_dir / "orchestrator.log",
        created_files_log=feature_dir / "created_files.log",
    )


def create_feature_files(
    project_dir: Path,
    feature_dir: Path,
    prompt: str,
    session_name: str,
    product_manager: bool = False,
) -> RuntimeFiles:
    feature_dir.mkdir(parents=True, exist_ok=False)
    files = _make_runtime_files(project_dir, feature_dir)

    _context_template = (
        Path(__file__).resolve().parent.parent / "prompts" / "context.md"
    ).read_text(encoding="utf-8")
    files.context.write_text(
        _context_template.format_map({"session_name": session_name, "feature_dir": feature_dir}),
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
    state = {
        "feature_dir": str(feature_dir),
        "phase": "product_management" if product_manager else "planning",
        "product_manager": bool(product_manager),
        "last_event": "feature_created",
        "subplan_count": 0,
        "completed_subplans": [],
        "review_iteration": 0,
        "implementation_group_total": 0,
        "implementation_group_index": 0,
        "implementation_group_mode": None,
        "implementation_active_plan_ids": [],
        "implementation_completed_group_ids": [],
        "updated_at": now_iso(),
        "updated_by": "pipeline",
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


def infer_resume_phase(feature_dir: Path, state: dict[str, Any]) -> str:
    for key in ("research_tasks", "web_research_tasks"):
        tasks = state.get(key)
        if isinstance(tasks, dict):
            state[key] = {
                str(topic): str(status)
                for topic, status in tasks.items()
                if str(status) != "dispatched"
            }

    product_management_done = feature_dir / SESSION_DIR_NAMES["product_management"] / "done"
    if bool(state.get("product_manager")) and not product_management_done.exists():
        return "product_management"

    phase = str(state.get("phase", "planning"))
    if phase != "failed":
        return phase

    planning_dir = feature_dir / SESSION_DIR_NAMES["planning"]
    implementation_dir = feature_dir / SESSION_DIR_NAMES["implementation"]
    review_dir = feature_dir / SESSION_DIR_NAMES["review"]

    plan_path = planning_dir / "plan.md"
    if not plan_path.exists():
        return "planning"

    plan_meta_path = planning_dir / "plan_meta.json"
    plan_meta: dict[str, Any] = {}
    if plan_meta_path.exists():
        try:
            plan_meta = json.loads(plan_meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan_meta = {}
        if bool(plan_meta.get("needs_design")) and not (feature_dir / SESSION_DIR_NAMES["design"] / "design.md").exists():
            return "designing"

    subplan_count_raw = state.get("subplan_count")
    try:
        subplan_count = int(subplan_count_raw)
    except (TypeError, ValueError):
        subplan_count = 0
    if subplan_count < 0:
        subplan_count = 0

    fixing_iteration = (review_dir / "fix_request.md").exists() and int(state.get("review_iteration", 0)) > 0
    if fixing_iteration:
        done_complete = (implementation_dir / "done_1").exists()
        if not done_complete:
            return "fixing"
    elif subplan_count > 0:
        done_complete = all((implementation_dir / f"done_{index}").exists() for index in range(1, subplan_count + 1))
    else:
        done_complete = any(implementation_dir.glob("done_*"))

    if not done_complete:
        return "implementing"

    review_path = review_dir / "review.md"
    if not review_path.exists():
        return "reviewing"

    verdict = parse_review_verdict(review_path.read_text(encoding="utf-8"))
    if verdict is None:
        return "reviewing"

    return "completing"


def cleanup_feature_dir(feature_dir: Path) -> None:
    try:
        shutil.rmtree(feature_dir)
        print(f"Cleaned up feature directory: {feature_dir}")
    except FileNotFoundError:
        print(f"Feature directory already removed: {feature_dir}")
    except OSError as exc:
        print(f"Failed to clean up feature directory {feature_dir}: {exc}")


def commit_changes(project_dir: Path, commit_message: str, commit_files: list[str]) -> str | None:
    if not commit_message.strip():
        print("Warning: commit_message is empty; skipping commit.")
        return None

    files = [path.strip() for path in commit_files if path and path.strip()]
    if not files:
        print("Warning: commit_files is empty; skipping commit.")
        return None

    try:
        add_result = subprocess.run(
            ["git", "add", *files],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        if add_result.stderr.strip():
            print(f"Warning: git add stderr: {add_result.stderr.strip()}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        print(f"Warning: failed to stage commit files: {stderr}")
        return None

    try:
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        if commit_result.stderr.strip():
            print(f"Warning: git commit stderr: {commit_result.stderr.strip()}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        print(f"Warning: failed to create commit: {stderr}")
        return None

    try:
        rev_parse = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        print(f"Warning: commit created but failed to read commit hash: {stderr}")
        return None

    commit_hash = rev_parse.stdout.strip()
    if not commit_hash:
        print("Warning: commit created but rev-parse returned an empty hash.")
        return None
    return commit_hash
