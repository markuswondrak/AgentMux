from __future__ import annotations

from pathlib import Path

from .models import RuntimeFiles

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_NO_CHANGES_FALLBACK = (
    "_No changes.md found. Treat this as missing feedback context"
    " and ask the user to restate changes if required._"
)


def _load_template(subdir: str, name: str) -> str:
    return (PROMPTS_DIR / subdir / f"{name}.md").read_text(encoding="utf-8")


def write_prompt_file(feature_dir: Path, name: str, content: str) -> Path:
    prompt_path = feature_dir / name
    prompt_path.write_text(content, encoding="utf-8")
    return prompt_path


def build_architect_prompt(files: RuntimeFiles, state_target: str, is_review: bool = False) -> str:
    if is_review:
        return _load_template("commands", "review").format_map({
            "feature_dir": files.feature_dir,
            "state_target": state_target,
        })
    return _load_template("agents", "architect").format_map({
        "feature_dir": files.feature_dir,
        "state_target": state_target,
    })


def build_coder_prompt(files: RuntimeFiles, state_target: str) -> str:
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"update state.json so that `status` becomes `{state_target}`. "
        "This must be the very last action you take. Do not do anything after writing the status."
    )
    completion_constraints = "\n".join([
        f"- Do not change the status to anything else.",
        "- Do not touch the status file until the implementation is fully complete.",
    ])
    return _load_template("agents", "coder").format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "plan_file": "plan.md",
        "completion_instruction": completion_instruction,
        "completion_constraints": completion_constraints,
    })


def build_coder_subplan_prompt(
    files: RuntimeFiles,
    subplan_path: Path,
    subplan_index: int,
    state_target: str,
) -> str:
    _ = state_target
    marker_name = f"done_{subplan_index}"
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"create the completion marker file `{marker_name}` in the session directory "
        "and leave it empty. This must be the very last action you take."
    )
    completion_constraints = "\n".join([
        "- Do not update state.json in parallel coder mode.",
        "- Do not write anything to the marker file; create it as an empty file.",
    ])
    return _load_template("agents", "coder").format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "plan_file": subplan_path.name,
        "completion_instruction": completion_instruction,
        "completion_constraints": completion_constraints,
    })


def build_fix_prompt(files: RuntimeFiles, state_target: str) -> str:
    return _load_template("commands", "fix").format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "state_target": state_target,
    })


def build_confirmation_prompt(files: RuntimeFiles, approved_target: str, changes_target: str) -> str:
    return _load_template("commands", "confirmation").format_map({
        "feature_dir": files.feature_dir,
        "approved_target": approved_target,
        "changes_target": changes_target,
    })


def build_change_prompt(files: RuntimeFiles, state_target: str) -> str:
    requirements_text = files.requirements.read_text(encoding="utf-8")
    plan_text = files.plan.read_text(encoding="utf-8")
    changes_text = (
        files.changes.read_text(encoding="utf-8")
        if files.changes.exists()
        else _NO_CHANGES_FALLBACK
    )
    text = _load_template("commands", "change").format_map({
        "feature_dir": files.feature_dir,
        "state_target": state_target,
    })
    return (
        text
        .replace("<<<REQUIREMENTS_TEXT>>>", requirements_text)
        .replace("<<<PLAN_TEXT>>>", plan_text)
        .replace("<<<CHANGES_TEXT>>>", changes_text)
    )
