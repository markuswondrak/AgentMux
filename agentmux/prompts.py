from __future__ import annotations

import subprocess
from pathlib import Path

from .models import RuntimeFiles

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_CHANGED_FILES_FALLBACK = "_Unable to read changed files from git status._"


def _load_template(subdir: str, name: str, project_dir: Path | None = None) -> str:
    template = (PROMPTS_DIR / subdir / f"{name}.md").read_text(encoding="utf-8")
    project_instructions = ""
    if project_dir is not None:
        project_prompt = project_dir / ".agentmux" / "prompts" / subdir / f"{name}.md"
        if project_prompt.is_file():
            project_instructions = project_prompt.read_text(encoding="utf-8")
            project_instructions = project_instructions.replace("{", "{{").replace("}", "}}")
    return template.replace("{project_instructions}", project_instructions)


def write_prompt_file(feature_dir: Path, name: str, content: str) -> Path:
    prompt_path = feature_dir / name
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(content, encoding="utf-8")
    return prompt_path


def build_architect_prompt(files: RuntimeFiles) -> str:
    return _load_template(
        "agents",
        "architect",
        project_dir=files.project_dir,
    ).format_map({"feature_dir": files.feature_dir})


def build_product_manager_prompt(files: RuntimeFiles) -> str:
    return _load_template(
        "agents",
        "product-manager",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
    })


def build_reviewer_prompt(files: RuntimeFiles, is_review: bool = False) -> str:
    if is_review:
        return _load_template(
            "commands",
            "review",
            project_dir=files.project_dir,
        ).format_map({"feature_dir": files.feature_dir})
    return _load_template(
        "agents",
        "reviewer",
        project_dir=files.project_dir,
    ).format_map({"feature_dir": files.feature_dir})


def build_coder_prompt(files: RuntimeFiles) -> str:
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        "create the completion marker file `implementation/done_1` in the session directory "
        "and leave it empty. This must be the very last action you take."
    )
    completion_constraints = "\n".join([
        "- Do not update state.json from the coder step.",
        "- Do not write anything to the marker file; create it as an empty file.",
    ])
    return _load_template(
        "agents",
        "coder",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "plan_file": "planning/plan.md",
        "completion_instruction": completion_instruction,
        "completion_constraints": completion_constraints,
    })


def build_designer_prompt(files: RuntimeFiles) -> str:
    completion_instruction = (
        "FINAL STEP ONLY — after writing design.md and any optional design artifacts, "
        "stop. Do not update state.json or any workflow status from the designer step."
    )
    completion_constraints = "\n".join([
        "- Do not update state.json from the designer step.",
        "- `design.md` is the completion signal for this phase.",
    ])
    return _load_template(
        "agents",
        "designer",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "completion_instruction": completion_instruction,
        "completion_constraints": completion_constraints,
    })


def build_coder_subplan_prompt(
    files: RuntimeFiles,
    subplan_path: Path,
    subplan_index: int,
) -> str:
    marker_name = f"done_{subplan_index}"
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"create the completion marker file `implementation/{marker_name}` in the session directory "
        "and leave it empty. This must be the very last action you take."
    )
    completion_constraints = "\n".join([
        "- Do not update state.json in parallel coder mode.",
        "- Do not write anything to the marker file; create it as an empty file.",
    ])
    return _load_template(
        "agents",
        "coder",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "plan_file": f"planning/{subplan_path.name}",
        "completion_instruction": completion_instruction,
        "completion_constraints": completion_constraints,
    })


def build_fix_prompt(files: RuntimeFiles) -> str:
    return _load_template(
        "commands",
        "fix",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
    })


def build_docs_prompt(files: RuntimeFiles) -> str:
    return _load_template(
        "commands",
        "docs",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
    })


def build_confirmation_prompt(files: RuntimeFiles) -> str:
    changed_files = _CHANGED_FILES_FALLBACK
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=files.project_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = result.stdout.strip() or "_No changed files detected._"
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "(no stderr)"
        changed_files = f"{_CHANGED_FILES_FALLBACK}\nError: {stderr}"

    return _load_template(
        "commands",
        "confirmation",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "changed_files": changed_files,
    })


def build_code_researcher_prompt(topic: str, files: RuntimeFiles) -> str:
    return _load_template(
        "agents",
        "code-researcher",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "topic": topic,
    })


def build_web_researcher_prompt(topic: str, files: RuntimeFiles) -> str:
    return _load_template(
        "agents",
        "web-researcher",
        project_dir=files.project_dir,
    ).format_map({
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "topic": topic,
    })


def build_initial_prompts(files: RuntimeFiles) -> dict[str, Path]:
    """Build startup prompts and return their file paths."""
    return {
        "architect": write_prompt_file(
            files.feature_dir,
            "planning/architect_prompt.md",
            build_architect_prompt(files),
        ),
    }


def build_change_prompt(files: RuntimeFiles) -> str:
    return _load_template(
        "commands",
        "change",
        project_dir=files.project_dir,
    ).format_map({"feature_dir": files.feature_dir})
