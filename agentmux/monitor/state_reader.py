from __future__ import annotations

import fnmatch
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..agent_labels import role_display_label
from ..shared.models import SESSION_DIR_NAMES

ALWAYS_VISIBLE_STATES = [
    "product_management",
    "planning",
    "implementing",
    "reviewing",
    "completing",
    "done",
]
OPTIONAL_PHASES = {"designing", "fixing"}
PIPELINE_STATES = [
    "product_management",
    "planning",
    "designing",
    "implementing",
    "reviewing",
    "fixing",
    "completing",
    "done",
]
EVENT_LABELS: dict[str, str] = {
    "feature_created": "starting up",
    "resumed": "resumed",
    "plan_written": "plan ready",
    "design_written": "design ready",
    "research_dispatched": "researching…",
    "research_complete": "research done",
    "web_research_dispatched": "web research…",
    "web_research_complete": "web research done",
    "implementation_started": "coding…",
    "implementation_completed": "code done",
    "review_written": "review ready",
    "fix_requested": "fix needed",
    "fix_completed": "fix done",
    "approved": "approved ✓",
    "changes_requested": "changes asked",
    "plan_approved": "plan approved",
    "confirmation_sent": "awaiting ok",
    "pm_completed": "pm done",
}
MONITOR_FILE_EVENT_PATTERNS = (
    "requirements.md",
    "01_product_management/analysis.md",
    "02_planning/plan.md",
    "02_planning/tasks.md",
    "03_research/code-*/summary.md",
    "03_research/code-*/detail.md",
    "03_research/code-*/done",
    "03_research/web-*/summary.md",
    "03_research/web-*/detail.md",
    "03_research/web-*/done",
    "04_design/design.md",
    "05_implementation/done_*",
    "06_review/review.md",
    "06_review/fix_request.md",
    "08_completion/changes.md",
    "08_completion/approval.json",
)


@dataclass(frozen=True)
class MonitorLogEntry:
    timestamp: str
    time_str: str
    sort_order: int
    message: str
    phase_event: bool


def load_runtime_registry(runtime_state_path: Path) -> dict[str, str | None]:
    try:
        raw = json.loads(runtime_state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    registry = {
        str(role): pane_id if pane_id is None else str(pane_id)
        for role, pane_id in dict(raw.get("primary", {})).items()
    }
    for role, workers in dict(raw.get("parallel", {})).items():
        for worker_key, pane_id in dict(workers).items():
            registry[f"{role}_{worker_key}"] = None if pane_id is None else str(pane_id)
    return registry


def get_role_states(session_name: str, runtime_state_path: Path) -> dict[str, str]:
    registry = load_runtime_registry(runtime_state_path)
    if not registry:
        return {}

    try:
        result_all = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-a", "-F", "#{pane_id} #{pane_dead}"],
            capture_output=True,
            text=True,
            check=False,
        )
        all_ids = {
            parts[0]
            for line in result_all.stdout.splitlines()
            if (parts := line.strip().split()) and len(parts) >= 2 and parts[1] != "1"
        }

        result_pipeline = subprocess.run(
            ["tmux", "list-panes", "-t", f"{session_name}:pipeline", "-F", "#{pane_id} #{pane_dead}"],
            capture_output=True,
            text=True,
            check=False,
        )
        pipeline_ids = {
            parts[0]
            for line in result_pipeline.stdout.splitlines()
            if (parts := line.strip().split()) and len(parts) >= 2 and parts[1] != "1"
        }
    except Exception:
        return {}

    states: dict[str, str] = {}
    for role, pane_id in registry.items():
        if role.startswith("_") or pane_id is None:
            continue
        if pane_id in pipeline_ids:
            states[role] = "working"
        elif pane_id in all_ids:
            states[role] = "idle"
        else:
            states[role] = "inactive"
    return states


def get_role_labels(state_path: Path, runtime_state_path: Path) -> dict[str, str]:
    registry = load_runtime_registry(runtime_state_path)
    if not registry:
        return {}

    state = load_state(state_path)
    feature_dir = runtime_state_path.parent
    labels: dict[str, str] = {}
    for role_key in registry:
        if role_key.startswith("_"):
            continue
        role = role_key
        task_id: int | str | None = None
        if "_" in role_key:
            role, suffix = role_key.split("_", 1)
            task_id = int(suffix) if suffix.isdigit() else suffix
        labels[role_key] = role_display_label(feature_dir, role, task_id=task_id, state=state)
    return labels


def load_state(state_path: Path) -> dict:
    try:
        text = state_path.read_text(encoding="utf-8").strip()
        if text:
            return json.loads(text)
    except Exception:
        pass
    return {}


def status_color(status: str) -> str:
    if status == "done":
        return "\033[92m"
    if status == "failed":
        return "\033[31m"
    if status in ("completing", "reviewing"):
        return "\033[33m"
    return "\033[92m"


def trim_model(model: str, cli: str) -> str:
    prefix = f"{cli}-"
    if model.lower().startswith(prefix.lower()):
        model = model[len(prefix):]
    return model


def parse_timestamped_log_line(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw:
        return None
    parts = raw.split("  ", 1)
    if len(parts) != 2:
        return None
    timestamp, payload = parts
    if len(timestamp) != 19:
        return None
    return timestamp, payload.strip()


def should_render_file_event(relative_path: str) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in MONITOR_FILE_EVENT_PATTERNS)


def read_status_log_entries(log_path: Path) -> list[MonitorLogEntry]:
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception:
        return []

    entries: list[MonitorLogEntry] = []
    for line in text.splitlines():
        parsed = parse_timestamped_log_line(line)
        if parsed is None:
            continue
        timestamp, phase = parsed
        entries.append(
            MonitorLogEntry(
                timestamp=timestamp,
                time_str=timestamp[11:16],
                sort_order=0,
                message=f"> {format_event(phase)}",
                phase_event=True,
            )
        )
    return entries


def read_created_file_log_entries(log_path: Path) -> list[MonitorLogEntry]:
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception:
        return []

    entries: list[MonitorLogEntry] = []
    for line in text.splitlines():
        parsed = parse_timestamped_log_line(line)
        if parsed is None:
            continue
        timestamp, relative_path = parsed
        if not should_render_file_event(relative_path):
            continue
        entries.append(
            MonitorLogEntry(
                timestamp=timestamp,
                time_str=timestamp[11:16],
                sort_order=1,
                message=f"+ {relative_path}",
                phase_event=False,
            )
        )
    return entries


def read_monitor_log_entries(
    status_log_path: Path | None,
    created_files_log_path: Path | None,
    n: int,
) -> list[MonitorLogEntry]:
    entries: list[MonitorLogEntry] = []
    if status_log_path is not None:
        entries.extend(read_status_log_entries(status_log_path))
    if created_files_log_path is not None:
        entries.extend(read_created_file_log_entries(created_files_log_path))
    if not entries:
        return []
    ordered = sorted(entries, key=lambda entry: (entry.timestamp, entry.sort_order, entry.message))
    return ordered[-n:]


def read_feature_request(state_path: Path) -> str:
    requirements_path = state_path.parent / "requirements.md"
    try:
        lines = requirements_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    in_initial_request = False
    for line in lines:
        stripped = line.strip()
        if not in_initial_request:
            if stripped == "## Initial Request":
                in_initial_request = True
            continue
        if stripped:
            return stripped
    return ""


def format_event(raw: str) -> str:
    from ..workflow.interruptions import monitor_label_from_event

    interruption_label = monitor_label_from_event(raw)
    if interruption_label is not None:
        return interruption_label
    return EVENT_LABELS.get(raw, raw.replace("_", " "))
