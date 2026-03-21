from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .handlers import load_plan_meta, reset_markers, send_to_role, write_phase
from .plan_parser import split_plan_into_subplans
from .prompts import (
    build_architect_prompt,
    build_change_prompt,
    build_coder_prompt,
    build_coder_subplan_prompt,
    build_confirmation_prompt,
    build_designer_prompt,
    build_docs_prompt,
    build_fix_prompt,
    write_prompt_file,
)
from .state import cleanup_feature_dir, commit_changes, now_iso, write_state
from .transitions import EXIT_FAILURE, EXIT_SUCCESS, PipelineContext, file_signature, phase_input_changed


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


class PlanningPhase(Phase):
    name = "planning"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        is_replan = state.get("last_event") == "changes_requested" and ctx.files.changes.exists()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "changes_prompt.txt" if is_replan else "architect_prompt.md",
            build_change_prompt(ctx.files) if is_replan else build_architect_prompt(ctx.files),
        )
        send_to_role(ctx, "architect", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {
            "plan": file_signature(ctx.files.plan),
            "tasks": file_signature(ctx.files.tasks),
            "plan_meta": file_signature(ctx.files.feature_dir / "plan_meta.json"),
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        plan_sig = file_signature(ctx.files.plan)
        tasks_sig = file_signature(ctx.files.tasks)
        meta_sig = file_signature(ctx.files.feature_dir / "plan_meta.json")
        if all(
            phase_input_changed(ctx, key, value)
            for key, value in {
                "plan": plan_sig,
                "tasks": tasks_sig,
                "plan_meta": meta_sig,
            }.items()
        ):
            return "plan_written"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "plan_written":
            return None
        meta = load_plan_meta(ctx.files.feature_dir)
        needs_design = bool(meta.get("needs_design")) and "designer" in ctx.agents
        if ctx.files.changes.exists():
            ctx.files.changes.unlink()
        write_phase(
            ctx,
            state,
            "designing" if needs_design else "implementing",
            "plan_written",
        )
        return None


class DesigningPhase(Phase):
    name = "designing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "designer_prompt.md",
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
        reset_markers(ctx.files.feature_dir, "done_*")

        subplan_paths = split_plan_into_subplans(ctx.files.plan, ctx.files.feature_dir)
        subplan_count = len(subplan_paths)
        state["subplan_count"] = subplan_count
        state["updated_at"] = now_iso()
        state["updated_by"] = "pipeline"
        write_state(ctx.files.state, state)

        if subplan_count == 1:
            prompt_file = write_prompt_file(
                ctx.files.feature_dir,
                "coder_prompt.md",
                build_coder_prompt(ctx.files),
            )
            send_to_role(ctx, "coder", prompt_file)
            return

        prompt_files: list[Path] = []
        for subplan_index, subplan_path in enumerate(subplan_paths, start=1):
            prompt_files.append(
                write_prompt_file(
                    ctx.files.feature_dir,
                    f"coder_prompt_{subplan_index}.txt",
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
            f"done_{idx}": file_signature(ctx.files.feature_dir / f"done_{idx}")
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
                file_signature(ctx.files.feature_dir / f"done_{idx}"),
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
            "review_prompt.md",
            build_architect_prompt(ctx.files, is_review=True),
        )
        send_to_role(ctx, "architect", prompt_file)

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
        reset_markers(ctx.files.feature_dir, "done_*")
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "fix_prompt.txt",
            build_fix_prompt(ctx.files),
        )
        send_to_role(ctx, "coder", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        count = max(1, int(state.get("subplan_count", 1)))
        return {
            f"done_{idx}": file_signature(ctx.files.feature_dir / f"done_{idx}")
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
                file_signature(ctx.files.feature_dir / f"done_{idx}"),
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
        docs_done = ctx.files.feature_dir / "docs_done"
        if docs_done.exists():
            docs_done.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "docs_prompt.txt",
            build_docs_prompt(ctx.files),
        )
        send_to_role(ctx, "docs", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {"docs_done": file_signature(ctx.files.feature_dir / "docs_done")}

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        if phase_input_changed(ctx, "docs_done", file_signature(ctx.files.feature_dir / "docs_done")):
            return "docs_completed"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event != "docs_completed":
            return None
        ctx.runtime.deactivate("docs")
        write_phase(ctx, state, "completing", "docs_completed")
        return None


class CompletingPhase(Phase):
    name = "completing"

    def on_enter(self, state: dict, ctx: PipelineContext) -> None:
        _ = state
        approval_path = ctx.files.feature_dir / "approval.json"
        if approval_path.exists():
            approval_path.unlink()
        prompt_file = write_prompt_file(
            ctx.files.feature_dir,
            "confirmation_prompt.md",
            build_confirmation_prompt(ctx.files),
        )
        send_to_role(ctx, "architect", prompt_file)

    def snapshot_inputs(self, state: dict, ctx: PipelineContext) -> dict[str, str | None]:
        _ = state
        return {
            "approval": file_signature(ctx.files.feature_dir / "approval.json"),
            "changes": file_signature(ctx.files.changes),
        }

    def detect_event(self, state: dict, ctx: PipelineContext) -> str | None:
        _ = state
        approval_path = ctx.files.feature_dir / "approval.json"
        if phase_input_changed(ctx, "approval", file_signature(approval_path)):
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
            if payload.get("action") == "approve":
                return "approval_received"
        if phase_input_changed(ctx, "changes", file_signature(ctx.files.changes)):
            return "changes_requested"
        return None

    def handle_event(self, state: dict, event: str, ctx: PipelineContext) -> str | None:
        if event == "approval_received":
            approval_path = ctx.files.feature_dir / "approval.json"
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
            commit_hash = commit_changes(
                ctx.files.project_dir,
                str(payload.get("commit_message", "")).strip(),
                [
                    str(path).strip()
                    for path in payload.get("commit_files", [])
                    if str(path).strip()
                ],
            )
            if commit_hash is not None:
                print("Completion approved and commit created.")
                print(f"Commit hash: {commit_hash}")
            else:
                print("Completion approved, but commit step failed or was skipped.")
            cleanup_feature_dir(ctx.files.feature_dir)
            return EXIT_SUCCESS

        if event != "changes_requested":
            return None
        ctx.runtime.deactivate_many(("coder", "docs", "designer"))
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
