from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from .handlers import load_plan_meta, reset_markers, send_to_role, write_phase
from .plan_parser import split_plan_into_subplans
from .prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_code_researcher_prompt,
    build_coder_prompt,
    build_coder_subplan_prompt,
    build_confirmation_prompt,
    build_designer_prompt,
    build_docs_prompt,
    build_fix_prompt,
    build_product_manager_prompt,
    build_reviewer_prompt,
    build_web_researcher_prompt,
    write_prompt_file,
)
from .state import cleanup_feature_dir, commit_changes, feature_slug_from_dir, now_iso, write_state
from .tmux import send_text
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext, file_signature, phase_input_changed


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
                    f"research/code-{t}/prompt.md",
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
            owner_pane = getattr(ctx.runtime, "primary_panes", {}).get(owner_role)
            if owner_pane:
                send_text(
                    owner_pane,
                    (
                        f"Code-research on '{topic}' is complete. Results are in "
                        f"research/code-{topic}/summary.md and research/code-{topic}/detail.md."
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
                    f"research/web-{t}/prompt.md",
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
            owner_pane = getattr(ctx.runtime, "primary_panes", {}).get(owner_role)
            if owner_pane:
                send_text(
                    owner_pane,
                    (
                        f"Web research on '{topic}' is complete. Results are in "
                        f"research/web-{topic}/summary.md and research/web-{topic}/detail.md."
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
            "product_management/product_manager_prompt.md",
            build_product_manager_prompt(ctx.files),
        )
        send_to_role(ctx, "product-manager", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        snapshot = {
            "pm_done": file_signature(ctx.files.feature_dir / "product_management" / "done"),
        }
        snapshot.update(self._research_snapshot(ctx))
        return snapshot

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        if phase_input_changed(
            ctx,
            "pm_done",
            file_signature(ctx.files.feature_dir / "product_management" / "done"),
        ):
            return "pm_completed"
        return self._detect_research_event(state, ctx)

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event == "pm_completed":
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
            f"planning/{'changes_prompt.txt' if is_replan else 'architect_prompt.md'}",
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
        _ = state
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "design/designer_prompt.md",
            build_designer_prompt(ctx.files),
        )
        send_to_role(ctx, "designer", prompt_file)

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

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        reset_markers(ctx.files.implementation_dir, "done_*")

        subplan_paths = split_plan_into_subplans(ctx.files.plan, ctx.files.planning_dir)
        subplan_count = len(subplan_paths)
        state["subplan_count"] = subplan_count
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(ctx.files.state, state)

        if subplan_count == 1:
            prompt_file = write_prompt_file(
                ctx.files.feature_dir,
                "implementation/coder_prompt.md",
                build_coder_prompt(ctx.files),
            )
            send_to_role(ctx, "coder", prompt_file)
            return

        prompt_files: list[Path] = []
        for subplan_index, subplan_path in enumerate(subplan_paths, start=1):
            prompt_files.append(
                write_prompt_file(
                    ctx.files.feature_dir,
                    f"implementation/coder_prompt_{subplan_index}.txt",
                    build_coder_subplan_prompt(
                        ctx.files,
                        subplan_path=subplan_path,
                        subplan_index=subplan_index,
                    ),
                )
            )

        ctx.runtime.send_many("coder", prompt_files)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        count = max(1, int(state.get("subplan_count", 1)))
        return {
            f"done_{idx}": file_signature(ctx.files.implementation_dir / f"done_{idx}")
            for idx in range(1, count + 1)
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        count = max(1, int(state.get("subplan_count", 1)))
        if count <= 0:
            return None
        done = [
            phase_input_changed(
                ctx,
                f"done_{idx}",
                file_signature(ctx.files.implementation_dir / f"done_{idx}"),
            )
            for idx in range(1, count + 1)
        ]
        if all(done):
            return "implementation_completed"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "implementation_completed":
            return None
        ctx.runtime.finish_many("coder")
        ctx.runtime.deactivate("coder")
        write_phase(ctx, state, "reviewing", "implementation_completed")
        return None


class ReviewingPhase(Phase):
    name = "reviewing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state
        if ctx.files.review.exists():
            ctx.files.review.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "review/review_prompt.md",
            build_reviewer_prompt(ctx.files, is_review=True),
        )
        send_to_role(ctx, "reviewer", prompt_file)

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
            next_phase = "documenting" if "docs" in ctx.agents else "completing"
            write_phase(ctx, state, next_phase, "review_passed")
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
        _ = state
        reset_markers(ctx.files.implementation_dir, "done_*")
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "review/fix_prompt.txt",
            build_fix_prompt(ctx.files),
        )
        send_to_role(ctx, "coder", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        count = max(1, int(state.get("subplan_count", 1)))
        return {
            f"done_{idx}": file_signature(ctx.files.implementation_dir / f"done_{idx}")
            for idx in range(1, count + 1)
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        count = max(1, int(state.get("subplan_count", 1)))
        if count <= 0:
            return None
        done = [
            phase_input_changed(
                ctx,
                f"done_{idx}",
                file_signature(ctx.files.implementation_dir / f"done_{idx}"),
            )
            for idx in range(1, count + 1)
        ]
        if all(done):
            return "implementation_completed"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "implementation_completed":
            return None
        ctx.runtime.finish_many("coder")
        ctx.runtime.deactivate("coder")
        write_phase(ctx, state, "reviewing", "implementation_completed")
        return None


class DocumentingPhase(Phase):
    name = "documenting"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state
        docs_done = ctx.files.docs_dir / "docs_done"
        if docs_done.exists():
            docs_done.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "docs/docs_prompt.txt",
            build_docs_prompt(ctx.files),
        )
        send_to_role(ctx, "docs", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {"docs_done": file_signature(ctx.files.docs_dir / "docs_done")}

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        if phase_input_changed(ctx, "docs_done", file_signature(ctx.files.docs_dir / "docs_done")):
            return "docs_completed"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "docs_completed":
            return None
        ctx.runtime.kill_primary("docs")
        write_phase(ctx, state, "completing", "docs_completed")
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
            "completion/confirmation_prompt.md",
            build_confirmation_prompt(ctx.files),
        )
        send_to_role(ctx, "reviewer", prompt_file)

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
            changed_paths = _parse_changed_paths(_git_status_porcelain(ctx.files.project_dir))
            exclude_files = {
                str(path).strip()
                for path in payload.get("exclude_files", [])
                if str(path).strip()
            }
            commit_hash = commit_changes(
                ctx.files.project_dir,
                str(payload.get("commit_message", "")).strip(),
                [path for path in changed_paths if path not in exclude_files],
            )
            if commit_hash is not None:
                print("Completion approved and commit created.")
                print(f"Commit hash: {commit_hash}")
                if state.get("gh_available"):
                    from .github import create_branch_and_pr

                    issue_number_raw = state.get("issue_number")
                    issue_number = str(issue_number_raw) if issue_number_raw is not None else None
                    result = create_branch_and_pr(
                        project_dir=ctx.files.project_dir,
                        feature_slug=feature_slug_from_dir(ctx.files.feature_dir),
                        github_config=ctx.github_config,
                        issue_number=issue_number,
                        feature_dir=ctx.files.feature_dir,
                    )
                    if result:
                        print(f"PR created: {result['pr_url']}")
                    else:
                        print("PR creation failed (commit preserved).")
                cleanup_feature_dir(ctx.files.feature_dir)
            else:
                print("Completion approved, but commit step failed or was skipped. Feature directory retained.")
            return EXIT_SUCCESS

        if event != "changes_requested":
            return None
        ctx.runtime.deactivate_many(("reviewer", "coder", "docs", "designer"))
        ctx.runtime.finish_many("coder")
        state["subplan_count"] = 0
        state["review_iteration"] = 0
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
        DocumentingPhase(),
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
