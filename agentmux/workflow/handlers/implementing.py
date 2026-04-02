"""Event-driven handler for implementing phase."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from agentmux.workflow.event_router import (
    PhaseHandler,
    WorkflowEvent,
    extract_subplan_index,
)
from agentmux.workflow.execution_plan import load_execution_plan
from agentmux.workflow.phase_helpers import (
    filter_file_created_event,
    reset_markers,
    send_to_role,
)
from agentmux.workflow.plan_parser import coder_label_for_subplan
from agentmux.workflow.prompts import build_coder_subplan_prompt, write_prompt_file
from agentmux.agent_labels import format_agent_label
from agentmux.runtime import ParallelPromptSpec

if TYPE_CHECKING:
    from agentmux.workflow.transitions import PipelineContext


def _plan_index_from_name(plan_name: str) -> int:
    """Extract plan index from plan file name."""
    match = re.match(r"^plan_(\d+)\.md$", plan_name)
    if match is None:
        raise RuntimeError(
            f"Expected numbered plan file names like `plan_1.md`, got `{plan_name}`."
        )
    return int(match.group(1))


def _build_implementation_schedule(*, planning_dir: Path) -> list[dict[str, object]]:
    """Build implementation schedule from execution_plan.json."""
    execution_plan = load_execution_plan(planning_dir)

    schedule: list[dict[str, object]] = []
    all_indexes: list[int] = []
    for group in execution_plan.groups:
        group_indexes = [_plan_index_from_name(plan.file) for plan in group.plans]
        if group.mode == "serial" and len(group_indexes) != 1:
            raise RuntimeError(
                f"execution_plan.json group `{group.group_id}` uses mode `serial` and must reference exactly one plan."
            )
        all_indexes.extend(group_indexes)
        plan_paths = [planning_dir / plan.file for plan in group.plans]
        schedule.append(
            {
                "group_id": group.group_id,
                "mode": group.mode,
                "plan_paths": plan_paths,
                "plan_ids": [Path(plan.file).stem for plan in group.plans],
                "plan_names": [
                    plan.name or coder_label_for_subplan(planning_dir, index)
                    for plan, index in zip(group.plans, group_indexes)
                ],
                "marker_indexes": group_indexes,
            }
        )

    if len(all_indexes) != len(set(all_indexes)):
        raise RuntimeError(
            "execution_plan.json must not reuse plan files across groups."
        )
    if all_indexes:
        max_index = max(all_indexes)
        missing_indexes = sorted(set(range(1, max_index + 1)) - set(all_indexes))
        if missing_indexes:
            missing_csv = ", ".join(str(index) for index in missing_indexes)
            raise RuntimeError(
                f"execution_plan.json plan indexes must be contiguous from 1..{max_index}; missing: {missing_csv}."
            )
    return schedule


def _group_marker_paths(
    implementation_dir: Path,
    group: dict[str, object],
) -> list[Path]:
    """Get marker paths for a group."""
    marker_indexes = [int(index) for index in list(group["marker_indexes"])]
    return [implementation_dir / f"done_{index}" for index in marker_indexes]


def _all_markers_complete(
    implementation_dir: Path,
    group: dict[str, object],
) -> bool:
    """Check if all markers for a group are complete."""
    return all(path.exists() for path in _group_marker_paths(implementation_dir, group))


def _first_incomplete_group_index(
    implementation_dir: Path,
    schedule: list[dict[str, object]],
) -> int | None:
    """Find the first incomplete group index."""
    for index, group in enumerate(schedule):
        if not _all_markers_complete(implementation_dir, group):
            return index
    return None


def _set_implementation_progress(
    state: dict,
    schedule: list[dict[str, object]],
    active_group_index: int | None,
) -> None:
    """Set implementation progress in state."""
    group_total = len(schedule)
    state["implementation_group_total"] = group_total

    if group_total == 0:
        state["implementation_group_index"] = 0
        state["implementation_group_mode"] = None
        state["implementation_active_plan_ids"] = []
        state["implementation_completed_group_ids"] = []
        return

    if active_group_index is None:
        state["implementation_group_index"] = group_total
        state["implementation_group_mode"] = None
        state["implementation_active_plan_ids"] = []
        state["implementation_completed_group_ids"] = [
            str(group["group_id"]) for group in schedule
        ]
        return

    state["implementation_group_index"] = active_group_index + 1
    state["implementation_group_mode"] = str(schedule[active_group_index]["mode"])
    state["implementation_active_plan_ids"] = list(
        schedule[active_group_index]["plan_ids"]
    )
    state["implementation_completed_group_ids"] = [
        str(schedule[index]["group_id"]) for index in range(active_group_index)
    ]


class ImplementingHandler:
    """Event-driven handler for implementing phase."""

    def enter(self, state: dict, ctx: "PipelineContext") -> dict:
        """Called when entering implementing phase.

        Resets markers and dispatches first group.
        """
        if state.get("last_event") in {
            "plan_written",
            "design_written",
            "changes_requested",
        }:
            reset_markers(ctx.files.implementation_dir, "done_*")
        ctx.runtime.kill_primary("coder")

        schedule = _build_implementation_schedule(planning_dir=ctx.files.planning_dir)
        updates: dict[str, object] = {}
        updates["subplan_count"] = self._total_marker_count(schedule)
        updates["completed_subplans"] = []

        active_group_index = _first_incomplete_group_index(
            ctx.files.implementation_dir, schedule
        )
        _set_implementation_progress(updates, schedule, active_group_index)

        if active_group_index is not None:
            self._dispatch_active_group(ctx, schedule, active_group_index)

        return updates

    def handle_event(
        self,
        event: WorkflowEvent,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle events for implementing phase."""
        path = filter_file_created_event(event)
        if path is None:
            return {}, None

        # Check for subplan completion
        subplan_index = extract_subplan_index(path)
        if subplan_index is not None:
            return self._handle_subplan_completed(subplan_index, state, ctx)

        return {}, None

    def _handle_subplan_completed(
        self,
        subplan_index: int,
        state: dict,
        ctx: "PipelineContext",
    ) -> tuple[dict, str | None]:
        """Handle a subplan completion."""
        schedule = _build_implementation_schedule(planning_dir=ctx.files.planning_dir)
        if not schedule:
            return {}, "reviewing"

        group_index = int(state.get("implementation_group_index", 0))
        if group_index <= 0 or group_index > len(schedule):
            return {}, None

        active_group = schedule[group_index - 1]
        marker_indexes = [int(index) for index in list(active_group["marker_indexes"])]

        # Check if this subplan is part of the active group
        if subplan_index not in marker_indexes:
            return {}, None

        # Hide the task
        ctx.runtime.hide_task("coder", subplan_index)

        # Update completed subplans
        completed = self._completed_subplans(state)
        completed.add(subplan_index)
        updates = {"completed_subplans": sorted(completed)}

        # Check if all markers in the group are complete
        if not _all_markers_complete(ctx.files.implementation_dir, active_group):
            return updates, None

        # Group complete - move to next group or finish
        return self._handle_group_completed(state, ctx, schedule)

    def _handle_group_completed(
        self,
        state: dict,
        ctx: "PipelineContext",
        schedule: list[dict[str, object]],
    ) -> tuple[dict, str | None]:
        """Handle group completion."""
        next_group_index = _first_incomplete_group_index(
            ctx.files.implementation_dir, schedule
        )
        ctx.runtime.finish_many("coder")

        if next_group_index is None:
            # All groups complete
            _set_implementation_progress(state, schedule, active_group_index=None)
            updates = {
                "completed_subplans": [],
                "implementation_group_index": state.get("implementation_group_index"),
                "implementation_group_mode": state.get("implementation_group_mode"),
                "implementation_active_plan_ids": state.get(
                    "implementation_active_plan_ids"
                ),
                "implementation_completed_group_ids": state.get(
                    "implementation_completed_group_ids"
                ),
                "last_event": "implementation_completed",
            }
            ctx.runtime.deactivate("coder")
            return updates, "reviewing"

        # Move to next group
        _set_implementation_progress(
            state, schedule, active_group_index=next_group_index
        )
        updates = {
            "completed_subplans": [],
            "implementation_group_index": state.get("implementation_group_index"),
            "implementation_group_mode": state.get("implementation_group_mode"),
            "implementation_active_plan_ids": state.get(
                "implementation_active_plan_ids"
            ),
            "implementation_completed_group_ids": state.get(
                "implementation_completed_group_ids"
            ),
        }
        self._dispatch_active_group(ctx, schedule, next_group_index)
        return updates, None

    def _dispatch_active_group(
        self,
        ctx: "PipelineContext",
        schedule: list[dict[str, object]],
        active_group_index: int,
    ) -> None:
        """Dispatch prompts for the active group."""
        group = schedule[active_group_index]
        marker_indexes = [int(index) for index in list(group["marker_indexes"])]
        plan_paths = [Path(path) for path in list(group["plan_paths"])]
        plan_names = [
            None if name is None else str(name)
            for name in list(group.get("plan_names", []))
        ]

        pending: list[tuple[int, Path, str | None]] = [
            (index, path, plan_name)
            for index, path, plan_name in zip(marker_indexes, plan_paths, plan_names)
            if not (ctx.files.implementation_dir / f"done_{index}").exists()
        ]

        if not pending:
            return

        prompt_specs: list[ParallelPromptSpec] = []
        for marker_index, subplan_path, plan_name in pending:
            prompt_specs.append(
                ParallelPromptSpec(
                    task_id=marker_index,
                    prompt_file=write_prompt_file(
                        ctx.files.feature_dir,
                        ctx.files.relative_path(
                            ctx.files.implementation_dir
                            / f"coder_prompt_{marker_index}.txt"
                        ),
                        build_coder_subplan_prompt(
                            ctx.files,
                            subplan_path=subplan_path,
                            subplan_index=marker_index,
                        ),
                    ),
                    display_label=format_agent_label(
                        "coder",
                        plan_name
                        or coder_label_for_subplan(
                            ctx.files.planning_dir, marker_index
                        ),
                    ),
                )
            )

        if str(group["mode"]) == "parallel" and len(prompt_specs) > 1:
            ctx.runtime.send_many("coder", prompt_specs)
        else:
            send_to_role(
                ctx,
                "coder",
                prompt_specs[0].prompt_file,
                display_label=prompt_specs[0].display_label,
            )

    @staticmethod
    def _total_marker_count(schedule: list[dict[str, object]]) -> int:
        """Count total markers in schedule."""
        all_indexes: list[int] = []
        for group in schedule:
            all_indexes.extend(int(index) for index in list(group["marker_indexes"]))
        return max(all_indexes, default=1)

    @staticmethod
    def _completed_subplans(state: dict) -> set[int]:
        """Get set of completed subplan indexes."""
        completed: set[int] = set()
        for value in list(state.get("completed_subplans", [])):
            try:
                completed.add(int(value))
            except (TypeError, ValueError):
                continue
        return completed
