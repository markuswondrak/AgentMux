from __future__ import annotations

import json
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ..agent_labels import format_agent_label, role_display_label
from ..integrations.completion import CompletionService
from ..runtime import ParallelPromptSpec
from ..sessions.state_store import now_iso, write_state
from .execution_plan import load_execution_plan
from .handlers import load_plan_meta, reset_markers, send_to_role, write_phase
from .plan_parser import coder_label_for_subplan, split_plan_into_subplans
from .preference_memory import (
    apply_preference_proposal,
    load_preference_proposal,
    proposal_artifact_for_source,
)
from .prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_code_researcher_prompt,
    build_coder_prompt,
    build_coder_subplan_prompt,
    build_confirmation_prompt,
    build_designer_prompt,
    build_fix_prompt,
    build_product_manager_prompt,
    build_reviewer_prompt,
    build_web_researcher_prompt,
    write_prompt_file,
)
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext, file_signature, phase_input_changed

COMPLETION_SERVICE = CompletionService()


def _git_status_porcelain(project_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        print(f"Warning: failed to read git status for commit selection: {stderr}")
        return ""


def _parse_changed_paths(status_output: str) -> list[str]:
    paths: list[str] = []
    for raw_line in status_output.splitlines():
        if not raw_line.strip():
            continue
        entry = raw_line[3:] if len(raw_line) >= 4 else raw_line
        path = entry.split(" -> ", maxsplit=1)[-1].strip()
        if path:
            paths.append(path)
    return paths


def _apply_approved_preferences(ctx: PipelineContext, source_role: str) -> None:
    proposal_path = proposal_artifact_for_source(ctx.files, source_role)
    proposal = load_preference_proposal(proposal_path)
    if proposal is None:
        return
    apply_preference_proposal(ctx.files.project_dir, proposal)


def _reset_implementation_progress(state: dict) -> None:
    state["completed_subplans"] = []
    state["implementation_group_total"] = 0
    state["implementation_group_index"] = 0
    state["implementation_group_mode"] = None
    state["implementation_active_plan_ids"] = []
    state["implementation_completed_group_ids"] = []


def _set_implementation_progress(
    state: dict,
    schedule: list[dict[str, object]],
    active_group_index: int | None,
) -> None:
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
    state["implementation_active_plan_ids"] = list(schedule[active_group_index]["plan_ids"])
    state["implementation_completed_group_ids"] = [
        str(schedule[index]["group_id"]) for index in range(active_group_index)
    ]


def _plan_index_from_name(plan_name: str) -> int:
    match = re.match(r"^plan_(\d+)\.md$", plan_name)
    if match is None:
        raise RuntimeError(
            f"Expected numbered plan file names like `plan_1.md`, got `{plan_name}`."
        )
    return int(match.group(1))


def _build_implementation_schedule(
    *,
    plan_path: Path,
    planning_dir: Path,
) -> list[dict[str, object]]:
    execution_plan = load_execution_plan(planning_dir)
    if execution_plan is None:
        subplan_paths = split_plan_into_subplans(plan_path, planning_dir)
        if len(subplan_paths) == 1:
            return [
                {
                    "group_id": "group_1",
                    "mode": "serial",
                    "plan_paths": [plan_path],
                    "plan_ids": ["plan_1"],
                    "plan_names": [None],
                    "marker_indexes": [1],
                    "legacy_single_prompt": True,
                }
            ]
        marker_indexes = list(range(1, len(subplan_paths) + 1))
        return [
            {
                "group_id": "group_1",
                "mode": "parallel",
                "plan_paths": subplan_paths,
                "plan_ids": [f"plan_{index}" for index in marker_indexes],
                "plan_names": [coder_label_for_subplan(planning_dir, index) for index in marker_indexes],
                "marker_indexes": marker_indexes,
                "legacy_single_prompt": False,
            }
        ]

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
                "plan_names": [plan.name or coder_label_for_subplan(planning_dir, index) for plan, index in zip(group.plans, group_indexes)],
                "marker_indexes": group_indexes,
                "legacy_single_prompt": False,
            }
        )

    if len(all_indexes) != len(set(all_indexes)):
        raise RuntimeError("execution_plan.json must not reuse plan files across groups.")
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
    marker_indexes = [int(index) for index in list(group["marker_indexes"])]
    return [implementation_dir / f"done_{index}" for index in marker_indexes]


def _all_markers_complete(
    implementation_dir: Path,
    group: dict[str, object],
) -> bool:
    return all(path.exists() for path in _group_marker_paths(implementation_dir, group))


def _first_incomplete_group_index(
    implementation_dir: Path,
    schedule: list[dict[str, object]],
) -> int | None:
    for index, group in enumerate(schedule):
        if not _all_markers_complete(implementation_dir, group):
            return index
    return None


class Phase(ABC):
    name: str

    @abstractmethod
    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        ...

    @abstractmethod
    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        ...

    @abstractmethod
    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        ...

    @abstractmethod
    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        ...


class _ResearchDispatchMixin:
    @staticmethod
    def _parse_task_event(event: str, expected: str) -> str | None:
        prefix = f"{expected}:"
        if not event.startswith(prefix):
            return None
        topic = event[len(prefix):].strip()
        return topic or None

    def _research_snapshot(self, ctx: PipelineContext) -> dict[str, str | None]:
        snapshot: dict[str, str | None] = {}
        for request_path in sorted(ctx.files.research_dir.glob("code-*/request.md")):
            snapshot[f"{request_path.parent.name}/request.md"] = file_signature(request_path)
        for done_path in sorted(ctx.files.research_dir.glob("code-*/done")):
            snapshot[f"{done_path.parent.name}/done"] = file_signature(done_path)
        for request_path in sorted(ctx.files.research_dir.glob("web-*/request.md")):
            snapshot[f"{request_path.parent.name}/request.md"] = file_signature(request_path)
        for done_path in sorted(ctx.files.research_dir.glob("web-*/done")):
            snapshot[f"{done_path.parent.name}/done"] = file_signature(done_path)
        return snapshot

    def _detect_research_event(self, state: dict, ctx: PipelineContext) -> str | None:
        tracked_tasks = {
            str(topic): str(status)
            for topic, status in dict(state.get("research_tasks", {})).items()
        }
        any_code_dispatched = any(v == "dispatched" for v in tracked_tasks.values())
        if not any_code_dispatched:
            for request_path in sorted(ctx.files.research_dir.glob("code-*/request.md")):
                topic = request_path.parent.name.removeprefix("code-")
                if topic and topic not in tracked_tasks:
                    return "code_batch_requested"

        for done_path in sorted(ctx.files.research_dir.glob("code-*/done")):
            topic = done_path.parent.name.removeprefix("code-")
            if tracked_tasks.get(topic) == "dispatched":
                return f"task_completed:{topic}"

        tracked_web_tasks = {
            str(topic): str(status)
            for topic, status in dict(state.get("web_research_tasks", {})).items()
        }
        any_web_dispatched = any(v == "dispatched" for v in tracked_web_tasks.values())
        if not any_web_dispatched:
            for request_path in sorted(ctx.files.research_dir.glob("web-*/request.md")):
                topic = request_path.parent.name.removeprefix("web-")
                if topic and topic not in tracked_web_tasks:
                    return "web_batch_requested"

        for done_path in sorted(ctx.files.research_dir.glob("web-*/done")):
            topic = done_path.parent.name.removeprefix("web-")
            if tracked_web_tasks.get(topic) == "dispatched":
                return f"web_task_completed:{topic}"
        return None

    def _handle_research_event(
        self,
        state: dict,
        event: str,
        ctx: PipelineContext,
        owner_role: str,
    ) -> bool:
        if event == "code_batch_requested":
            research_tasks = {
                str(key): str(value)
                for key, value in dict(state.get("research_tasks", {})).items()
            }
            pending = [
                request_path.parent.name.removeprefix("code-")
                for request_path in sorted(ctx.files.research_dir.glob("code-*/request.md"))
                if (topic := request_path.parent.name.removeprefix("code-"))
                and topic not in research_tasks
            ]
            for t in pending:
                done_marker = ctx.files.research_dir / f"code-{t}" / "done"
                if done_marker.exists():
                    done_marker.unlink()
                prompt_file = write_prompt_file(
                    ctx.files.feature_dir,
                    ctx.files.relative_path(ctx.files.research_dir / f"code-{t}" / "prompt.md"),
                    build_code_researcher_prompt(t, ctx.files),
                )
                ctx.runtime.spawn_task("code-researcher", t, prompt_file)
                research_tasks[t] = "dispatched"
            state["research_tasks"] = research_tasks
            state["updated_at"] = now_iso()
            state["updated_by"] = "pipeline"
            write_state(ctx.files.state, state)
            return True

        topic = self._parse_task_event(event, "task_completed")
        if topic is not None:
            ctx.runtime.finish_task("code-researcher", topic)
            ctx.runtime.notify(
                owner_role,
                (
                    f"Code-research on '{topic}' is complete. Read "
                    f"{ctx.files.relative_path(ctx.files.research_dir / f'code-{topic}' / 'summary.md')} and continue from there."
                ),
            )
            research_tasks = {
                str(key): str(value)
                for key, value in dict(state.get("research_tasks", {})).items()
            }
            research_tasks[topic] = "done"
            state["research_tasks"] = research_tasks
            state["updated_at"] = now_iso()
            state["updated_by"] = "pipeline"
            write_state(ctx.files.state, state)
            return True

        if event == "web_batch_requested":
            web_research_tasks = {
                str(key): str(value)
                for key, value in dict(state.get("web_research_tasks", {})).items()
            }
            pending = [
                request_path.parent.name.removeprefix("web-")
                for request_path in sorted(ctx.files.research_dir.glob("web-*/request.md"))
                if (topic := request_path.parent.name.removeprefix("web-"))
                and topic not in web_research_tasks
            ]
            for t in pending:
                done_marker = ctx.files.research_dir / f"web-{t}" / "done"
                if done_marker.exists():
                    done_marker.unlink()
                prompt_file = write_prompt_file(
                    ctx.files.feature_dir,
                    ctx.files.relative_path(ctx.files.research_dir / f"web-{t}" / "prompt.md"),
                    build_web_researcher_prompt(t, ctx.files),
                )
                ctx.runtime.spawn_task("web-researcher", t, prompt_file)
                web_research_tasks[t] = "dispatched"
            state["web_research_tasks"] = web_research_tasks
            state["updated_at"] = now_iso()
            state["updated_by"] = "pipeline"
            write_state(ctx.files.state, state)
            return True

        topic = self._parse_task_event(event, "web_task_completed")
        if topic is not None:
            ctx.runtime.finish_task("web-researcher", topic)
            ctx.runtime.notify(
                owner_role,
                (
                    f"Web research on '{topic}' is complete. Read "
                    f"{ctx.files.relative_path(ctx.files.research_dir / f'web-{topic}' / 'summary.md')} and continue from there."
                ),
            )
            web_research_tasks = {
                str(key): str(value)
                for key, value in dict(state.get("web_research_tasks", {})).items()
            }
            web_research_tasks[topic] = "done"
            state["web_research_tasks"] = web_research_tasks
            state["updated_at"] = now_iso()
            state["updated_by"] = "pipeline"
            write_state(ctx.files.state, state)
            return True
        return False


class ProductManagementPhase(_ResearchDispatchMixin, Phase):
    name = "product_management"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.product_management_dir / "product_manager_prompt.md"),
            build_product_manager_prompt(ctx.files),
        )
        send_to_role(ctx, "product-manager", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        snapshot = {
            "pm_done": file_signature(ctx.files.product_management_dir / "done"),
        }
        snapshot.update(self._research_snapshot(ctx))
        return snapshot

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        if phase_input_changed(
            ctx,
            "pm_done",
            file_signature(ctx.files.product_management_dir / "done"),
        ):
            return "pm_completed"
        return self._detect_research_event(state, ctx)

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event == "pm_completed":
            _apply_approved_preferences(ctx, "product-manager")
            ctx.runtime.kill_primary("product-manager")
            write_phase(ctx, state, "planning", "pm_completed")
            return None
        self._handle_research_event(state, event, ctx, owner_role="product-manager")
        return None


class PlanningPhase(_ResearchDispatchMixin, Phase):
    name = "planning"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        is_replan = state.get("last_event") == "changes_requested" and ctx.files.changes.exists()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(
                ctx.files.planning_dir / ("changes_prompt.txt" if is_replan else "architect_prompt.md")
            ),
            build_change_prompt(ctx.files) if is_replan else build_architect_prompt(ctx.files),
        )
        send_to_role(ctx, "architect", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        snapshot: dict[str, str | None] = {
            "plan": file_signature(ctx.files.plan),
            "tasks": file_signature(ctx.files.tasks),
            "plan_meta": file_signature(ctx.files.planning_dir / "plan_meta.json"),
        }
        snapshot.update(self._research_snapshot(ctx))
        return snapshot

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        plan_sig = file_signature(ctx.files.plan)
        tasks_sig = file_signature(ctx.files.tasks)
        meta_sig = file_signature(ctx.files.planning_dir / "plan_meta.json")
        if all(
            phase_input_changed(ctx, key, value)
            for key, value in {
                "plan": plan_sig,
                "tasks": tasks_sig,
                "plan_meta": meta_sig,
            }.items()
        ):
            return "plan_written"
        return self._detect_research_event(state, ctx)

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event == "plan_written":
            _apply_approved_preferences(ctx, "architect")
            load_execution_plan(ctx.files.planning_dir)
            meta = load_plan_meta(ctx.files.planning_dir)
            needs_design = bool(meta.get("needs_design")) and "designer" in ctx.agents
            if ctx.files.changes.exists():
                ctx.files.changes.unlink()
            ctx.runtime.deactivate("architect")
            ctx.runtime.kill_primary("architect")
            write_phase(
                ctx,
                state,
                "designing" if needs_design else "implementing",
                "plan_written",
            )
            return None
        self._handle_research_event(state, event, ctx, owner_role="architect")
        return None


class DesigningPhase(Phase):
    name = "designing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.design_dir / "designer_prompt.md"),
            build_designer_prompt(ctx.files),
        )
        send_to_role(
            ctx,
            "designer",
            prompt_file,
            display_label=role_display_label(ctx.files.feature_dir, "designer", state=state),
        )

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {"design": file_signature(ctx.files.design)}

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        if phase_input_changed(ctx, "design", file_signature(ctx.files.design)):
            return "design_written"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "design_written":
            return None
        ctx.runtime.deactivate("designer")
        write_phase(ctx, state, "implementing", "design_written")
        return None


class ImplementingPhase(Phase):
    name = "implementing"

    @staticmethod
    def _schedule(ctx: PipelineContext) -> list[dict[str, object]]:
        return _build_implementation_schedule(
            plan_path=ctx.files.plan,
            planning_dir=ctx.files.planning_dir,
        )

    @staticmethod
    def _total_marker_count(schedule: list[dict[str, object]]) -> int:
        all_indexes: list[int] = []
        for group in schedule:
            all_indexes.extend(int(index) for index in list(group["marker_indexes"]))
        return max(all_indexes, default=1)

    @staticmethod
    def _completed_subplans(state: dict) -> set[int]:
        completed: set[int] = set()
        for value in list(state.get("completed_subplans", [])):
            try:
                completed.add(int(value))
            except (TypeError, ValueError):
                continue
        return completed

    def _dispatch_active_group(
        self,
        ctx: PipelineContext,
        schedule: list[dict[str, object]],
        active_group_index: int,
    ) -> None:
        group = schedule[active_group_index]
        marker_indexes = [int(index) for index in list(group["marker_indexes"])]
        plan_paths = [Path(path) for path in list(group["plan_paths"])]
        plan_names = [None if name is None else str(name) for name in list(group.get("plan_names", []))]
        pending: list[tuple[int, Path, str | None]] = [
            (index, path, plan_name)
            for index, path, plan_name in zip(marker_indexes, plan_paths, plan_names)
            if not (ctx.files.implementation_dir / f"done_{index}").exists()
        ]
        if not pending:
            return

        if bool(group["legacy_single_prompt"]):
            prompt_file = write_prompt_file(
                ctx.files.feature_dir,
                ctx.files.relative_path(ctx.files.implementation_dir / "coder_prompt.md"),
                build_coder_prompt(ctx.files),
            )
            send_to_role(
                ctx,
                "coder",
                prompt_file,
                display_label=role_display_label(ctx.files.feature_dir, "coder"),
            )
            return

        prompt_specs: list[ParallelPromptSpec] = []
        for marker_index, subplan_path, plan_name in pending:
            prompt_specs.append(
                ParallelPromptSpec(
                    task_id=marker_index,
                    prompt_file=write_prompt_file(
                        ctx.files.feature_dir,
                        ctx.files.relative_path(
                            ctx.files.implementation_dir / f"coder_prompt_{marker_index}.txt"
                        ),
                        build_coder_subplan_prompt(
                            ctx.files,
                            subplan_path=subplan_path,
                            subplan_index=marker_index,
                        ),
                    ),
                    display_label=format_agent_label(
                        "coder",
                        plan_name or coder_label_for_subplan(ctx.files.planning_dir, marker_index),
                    ),
                )
            )

        if str(group["mode"]) == "parallel" and len(prompt_specs) > 1:
            ctx.runtime.send_many("coder", prompt_specs)
            return
        send_to_role(
            ctx,
            "coder",
            prompt_specs[0].prompt_file,
            display_label=prompt_specs[0].display_label,
        )

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        if state.get("last_event") in {"plan_written", "design_written", "changes_requested"}:
            reset_markers(ctx.files.implementation_dir, "done_*")
        ctx.runtime.kill_primary("coder")

        schedule = self._schedule(ctx)
        state["subplan_count"] = self._total_marker_count(schedule)
        state["completed_subplans"] = []
        active_group_index = _first_incomplete_group_index(ctx.files.implementation_dir, schedule)
        _set_implementation_progress(state, schedule, active_group_index)
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(ctx.files.state, state)

        if active_group_index is None:
            return
        self._dispatch_active_group(ctx, schedule, active_group_index)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        schedule = self._schedule(ctx)
        if not schedule:
            return {}
        group_total = len(schedule)
        group_index = int(state.get("implementation_group_index", 0))
        if group_index <= 0:
            active_group = schedule[0]
        elif group_index > group_total:
            active_group = schedule[-1]
        else:
            active_group = schedule[group_index - 1]
        marker_indexes = [int(index) for index in list(active_group["marker_indexes"])]
        return {
            f"done_{index}": file_signature(ctx.files.implementation_dir / f"done_{index}")
            for index in marker_indexes
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        schedule = self._schedule(ctx)
        if not schedule:
            return "implementation_completed"
        group_index = int(state.get("implementation_group_index", 0))
        if group_index >= len(schedule) and not state.get("implementation_active_plan_ids"):
            return "implementation_completed"
        if group_index <= 0:
            return None
        active_group = schedule[group_index - 1]
        changed_done: list[int] = []
        for marker_index in [int(index) for index in list(active_group["marker_indexes"])]:
            if phase_input_changed(
                ctx,
                f"done_{marker_index}",
                file_signature(ctx.files.implementation_dir / f"done_{marker_index}"),
            ):
                changed_done.append(marker_index)
        if _all_markers_complete(ctx.files.implementation_dir, active_group):
            return "implementation_group_completed"
        if str(active_group["mode"]) != "parallel":
            return None
        completed = self._completed_subplans(state)
        for marker_index in changed_done:
            if marker_index not in completed:
                return f"subplan_completed:{marker_index}"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event.startswith("subplan_completed:"):
            try:
                task_id = int(event.split(":", 1)[1])
            except ValueError:
                return None
            ctx.runtime.hide_task("coder", task_id)
            completed = self._completed_subplans(state)
            completed.add(task_id)
            state["completed_subplans"] = sorted(completed)
            state["updated_at"] = now_iso()
            state["updated_by"] = "pipeline"
            write_state(ctx.files.state, state)
            return None
        if event not in {"implementation_group_completed", "implementation_completed"}:
            return None
        schedule = self._schedule(ctx)
        next_group_index = _first_incomplete_group_index(ctx.files.implementation_dir, schedule)
        ctx.runtime.finish_many("coder")

        if next_group_index is None:
            _set_implementation_progress(state, schedule, active_group_index=None)
            state["completed_subplans"] = []
            state["updated_at"] = now_iso()
            state["updated_by"] = "pipeline"
            write_state(ctx.files.state, state)
            ctx.runtime.deactivate("coder")
            write_phase(ctx, state, "reviewing", "implementation_completed")
            return None

        _set_implementation_progress(state, schedule, active_group_index=next_group_index)
        state["completed_subplans"] = []
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(ctx.files.state, state)
        self._dispatch_active_group(ctx, schedule, next_group_index)
        ctx.phase_baseline = self.snapshot_inputs(state, ctx)
        return None

class ReviewingPhase(Phase):
    name = "reviewing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        if ctx.files.review.exists():
            ctx.files.review.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.review_dir / "review_prompt.md"),
            build_reviewer_prompt(ctx.files, is_review=True),
        )
        send_to_role(
            ctx,
            "reviewer",
            prompt_file,
            display_label=role_display_label(ctx.files.feature_dir, "reviewer", state=state),
        )

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {"review": file_signature(ctx.files.review)}

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        if not phase_input_changed(ctx, "review", file_signature(ctx.files.review)):
            return None
        review_text = ctx.files.review.read_text(encoding="utf-8")
        first_line = review_text.splitlines()[0].strip().lower() if review_text.splitlines() else ""
        if first_line == "verdict: pass":
            return "review_passed"
        if first_line == "verdict: fail":
            return "review_failed"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event == "review_passed":
            ctx.runtime.finish_many("coder")
            ctx.runtime.kill_primary("coder")
            write_phase(ctx, state, "completing", "review_passed")
            return None
        if event != "review_failed":
            return None
        review_iteration = int(state.get("review_iteration", 0))
        if review_iteration >= ctx.max_review_iterations:
            write_phase(ctx, state, "completing", "review_failed")
            return None

        ctx.files.fix_request.write_text(
            ctx.files.review.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        state["review_iteration"] = review_iteration + 1
        write_phase(ctx, state, "fixing", "review_failed")
        return None


class FixingPhase(Phase):
    name = "fixing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        if state.get("last_event") == "review_failed":
            reset_markers(ctx.files.implementation_dir, "done_*")
        state["completed_subplans"] = []
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(ctx.files.state, state)
        ctx.runtime.kill_primary("coder")
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.review_dir / "fix_prompt.txt"),
            build_fix_prompt(ctx.files),
        )
        send_to_role(
            ctx,
            "coder",
            prompt_file,
            display_label=role_display_label(ctx.files.feature_dir, "coder", state=state),
        )

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {
            "done_1": file_signature(ctx.files.implementation_dir / "done_1"),
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        if (ctx.files.implementation_dir / "done_1").exists():
            return "implementation_completed"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "implementation_completed":
            return None
        ctx.runtime.finish_many("coder")
        ctx.runtime.deactivate("coder")
        write_phase(ctx, state, "reviewing", "implementation_completed")
        return None


class CompletingPhase(Phase):
    name = "completing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state
        approval_path = ctx.files.completion_dir / "approval.json"
        if approval_path.exists():
            approval_path.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            ctx.files.relative_path(ctx.files.completion_dir / "confirmation_prompt.md"),
            build_confirmation_prompt(ctx.files),
        )
        send_to_role(
            ctx,
            "reviewer",
            prompt_file,
            display_label=role_display_label(ctx.files.feature_dir, "reviewer", state=state),
        )

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {
            "approval": file_signature(ctx.files.completion_dir / "approval.json"),
            "changes": file_signature(ctx.files.changes),
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        approval_path = ctx.files.completion_dir / "approval.json"
        if phase_input_changed(ctx, "approval", file_signature(approval_path)):
            raw = approval_path.read_text(encoding="utf-8").strip()
            if not raw:
                return None
            payload = json.loads(raw)
            if payload.get("action") == "approve":
                return "approval_received"
        if phase_input_changed(ctx, "changes", file_signature(ctx.files.changes)):
            return "changes_requested"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event == "approval_received":
            approval_path = ctx.files.completion_dir / "approval.json"
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
            _apply_approved_preferences(ctx, "reviewer")
            changed_paths = _parse_changed_paths(_git_status_porcelain(ctx.files.project_dir))
            exclude_files = {
                str(path).strip()
                for path in payload.get("exclude_files", [])
                if str(path).strip()
            }
            result = COMPLETION_SERVICE.finalize_approval(
                files=ctx.files,
                github_config=ctx.github_config,
                gh_available=bool(state.get("gh_available")),
                issue_number=str(state.get("issue_number")) if state.get("issue_number") is not None else None,
                commit_message=str(payload.get("commit_message", "")).strip(),
                changed_paths=[path for path in changed_paths if path not in exclude_files],
            )
            if result.commit_hash is not None:
                print("Completion approved and commit created.")
                print(f"Commit hash: {result.commit_hash}")
                if bool(state.get("gh_available")):
                    if result.pr_url:
                        print(f"PR created: {result.pr_url}")
                    else:
                        print("PR creation failed (commit preserved).")
            else:
                print("Completion approved, but commit step failed or was skipped. Feature directory retained.")
            return EXIT_SUCCESS

        if event != "changes_requested":
            return None
        ctx.runtime.deactivate_many(("reviewer", "coder", "designer"))
        ctx.runtime.finish_many("coder")
        state["subplan_count"] = 0
        state["review_iteration"] = 0
        _reset_implementation_progress(state)
        write_phase(ctx, state, "planning", "changes_requested")
        return None


class FailedPhase(Phase):
    name = "failed"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state, ctx

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state, ctx
        return {}

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state, ctx
        return "failed"

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        _ = state, ctx
        if event == "failed":
            return EXIT_FAILURE
        return None


PHASES: dict[str, Phase] = {
    phase.name: phase
    for phase in (
        ProductManagementPhase(),
        PlanningPhase(),
        DesigningPhase(),
        ImplementingPhase(),
        ReviewingPhase(),
        FixingPhase(),
        CompletingPhase(),
        FailedPhase(),
    )
}


def get_phase(state: dict) -> Phase:
    phase_name = str(state.get("phase", ""))
    try:
        return PHASES[phase_name]
    except KeyError as exc:
        raise RuntimeError(f"Unknown phase: {phase_name!r}") from exc


def _enter_if_needed(phase: Phase, state: dict, ctx: PipelineContext) -> None:
    if ctx.entered_phase == phase.name:
        return
    phase.on_enter(state, ctx)
    ctx.entered_phase = phase.name
    ctx.phase_baseline = phase.snapshot_inputs(state, ctx)


def run_phase_cycle(state: dict, ctx: PipelineContext) -> str | None:
    phase = get_phase(state)
    _enter_if_needed(phase, state, ctx)
    event = phase.detect_event(state, ctx)
    if event is None:
        return None
    return phase.handle_event(state, event, ctx)
