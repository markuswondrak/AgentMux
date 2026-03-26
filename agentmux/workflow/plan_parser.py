from __future__ import annotations

import re
from pathlib import Path

from .execution_plan import load_execution_plan

SUBPLAN_HEADER_RE = re.compile(r"^##\s+Sub-plan\s+\d+\s*:\s+.+$")
SUBPLAN_HEADER_CAPTURE_RE = re.compile(r"^##\s+Sub-plan\s+(?P<index>\d+)\s*:\s+(?P<title>.+?)\s*$")


def read_subplan_title(subplan_path: Path) -> str | None:
    try:
        lines = subplan_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        match = SUBPLAN_HEADER_CAPTURE_RE.match(raw_line.strip())
        if match is None:
            continue
        title = match.group("title").strip()
        return title or None
    return None


def coder_label_for_subplan(planning_dir: Path, subplan_index: int | str) -> str:
    try:
        index = int(subplan_index)
    except (TypeError, ValueError):
        return f"plan {subplan_index}"
    try:
        execution_plan = load_execution_plan(planning_dir)
    except RuntimeError:
        execution_plan = None
    if execution_plan is not None:
        plan_file = f"plan_{index}.md"
        for group in execution_plan.groups:
            for plan in group.plans:
                if plan.file == plan_file and plan.name:
                    return plan.name
    title = read_subplan_title(planning_dir / f"plan_{index}.md")
    if title:
        return title
    return f"plan {index}"


def split_plan_into_subplans(plan_path: Path, planning_dir: Path) -> list[Path]:
    plan_text = plan_path.read_text(encoding="utf-8")
    lines = plan_text.splitlines(keepends=True)

    section_starts: list[int] = []
    for idx, line in enumerate(lines):
        if SUBPLAN_HEADER_RE.match(line.strip()):
            section_starts.append(idx)

    if not section_starts:
        return [plan_path]

    preamble = "".join(lines[: section_starts[0]])
    subplan_paths: list[Path] = []

    for index, section_start in enumerate(section_starts, start=1):
        section_end = section_starts[index] if index < len(section_starts) else len(lines)
        section_text = "".join(lines[section_start:section_end]).strip()

        content_parts: list[str] = []
        if preamble.strip():
            content_parts.append(preamble.strip())
        content_parts.append(section_text)
        subplan_text = "\n\n".join(content_parts).strip() + "\n"

        subplan_path = planning_dir / f"plan_{index}.md"
        subplan_path.write_text(subplan_text, encoding="utf-8")
        subplan_paths.append(subplan_path)

    return subplan_paths
