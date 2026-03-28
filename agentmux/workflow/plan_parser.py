from __future__ import annotations

import re
from pathlib import Path

from .execution_plan import load_execution_plan

def coder_label_for_subplan(planning_dir: Path, subplan_index: int | str) -> str:
    try:
        index = int(subplan_index)
    except (TypeError, ValueError):
        return f"plan {subplan_index}"
    try:
        execution_plan = load_execution_plan(planning_dir)
    except RuntimeError:
        return f"plan {index}"
    plan_file = f"plan_{index}.md"
    for group in execution_plan.groups:
        for plan in group.plans:
            if plan.file == plan_file:
                return plan.name or f"plan {index}"
    return f"plan {index}"
