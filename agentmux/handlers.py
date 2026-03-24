from __future__ import annotations

import json
from pathlib import Path

from .state import now_iso, write_state
from .transitions import PipelineContext


def send_to_role(ctx: PipelineContext, role: str, prompt_file: Path) -> None:
    ctx.runtime.send(role, prompt_file)


def write_phase(
    ctx: PipelineContext,
    state: dict,
    phase: str,
    last_event: str,
    **extra_fields: object,
) -> None:
    state["phase"] = phase
    state["last_event"] = last_event
    state["updated_at"] = now_iso()
    state["updated_by"] = "pipeline"
    state.update(extra_fields)
    write_state(ctx.files.state, state)
    ctx.entered_phase = None


def reset_markers(feature_dir: Path, pattern: str) -> None:
    for path in feature_dir.glob(pattern):
        if path.is_file():
            path.unlink()


def load_plan_meta(planning_dir: Path) -> dict[str, object]:
    path = planning_dir / "plan_meta.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
