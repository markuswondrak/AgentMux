from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..shared.models import RuntimeFiles

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SHARED_FRAGMENT_PATTERN = re.compile(r"\[\[shared:([a-z0-9][a-z0-9_-]*)\]\]")
_VALUE_PLACEHOLDER_PATTERN = re.compile(r"\[\[placeholder:([a-z0-9][a-z0-9_-]*)\]\]")
_MAX_SHARED_FRAGMENT_EXPANSION_DEPTH = 8
_PROJECT_INSTRUCTIONS_PLACEHOLDER = "[[placeholder:project_instructions]]"
_PROJECT_INSTRUCTIONS_PLACEHOLDER_LEGACY = "{project_instructions}"

_CHANGED_FILES_FALLBACK = "_Unable to read changed files from git status._"


def _load_shared_fragment(name: str) -> str:
    fragment_path = PROMPTS_DIR / "shared" / f"{name}.md"
    if not fragment_path.is_file():
        raise RuntimeError(f"Shared prompt fragment not found: {fragment_path}")
    return fragment_path.read_text(encoding="utf-8")


def _expand_shared_fragments(template: str) -> str:
    expanded = template

    for _ in range(_MAX_SHARED_FRAGMENT_EXPANSION_DEPTH):
        if _SHARED_FRAGMENT_PATTERN.search(expanded) is None:
            return expanded
        expanded = _SHARED_FRAGMENT_PATTERN.sub(
            lambda match: _load_shared_fragment(match.group(1)),
            expanded,
        )

    if _SHARED_FRAGMENT_PATTERN.search(expanded) is not None:
        raise RuntimeError(
            "Shared prompt fragment expansion exceeded maximum depth. "
            "Check for a recursive [[shared:...]] include chain.",
        )
    return expanded


def _load_template(subdir: str, name: str, project_dir: Path | None = None) -> str:
    template = (PROMPTS_DIR / subdir / f"{name}.md").read_text(encoding="utf-8")
    template = _expand_shared_fragments(template)
    project_instructions = ""
    if project_dir is not None:
        project_prompt = project_dir / ".agentmux" / "prompts" / subdir / f"{name}.md"
        if project_prompt.is_file():
            project_instructions = project_prompt.read_text(encoding="utf-8")
            project_instructions = project_instructions.replace("{", "{{").replace("}", "}}")
    return (
        template
        .replace(_PROJECT_INSTRUCTIONS_PLACEHOLDER, project_instructions)
        .replace(_PROJECT_INSTRUCTIONS_PLACEHOLDER_LEGACY, project_instructions)
    )


def _render_template(template: str, values: dict[str, object]) -> str:
    rendered = template.format_map(values)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(key)
        return str(values[key])

    return _VALUE_PLACEHOLDER_PATTERN.sub(_replace, rendered)


def write_prompt_file(feature_dir: Path, name: str, content: str) -> Path:
    prompt_path = feature_dir / name
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(content, encoding="utf-8")
    return prompt_path


def _build_coder_research_handoff(files: RuntimeFiles) -> str:
    research_dir = files.research_dir
    if not research_dir.is_dir():
        return ""

    references: list[str] = []
    for topic_dir in sorted(path for path in research_dir.iterdir() if path.is_dir()):
        done_path = topic_dir / "done"
        summary_path = topic_dir / "summary.md"
        detail_path = topic_dir / "detail.md"
        if not done_path.is_file() or not summary_path.is_file():
            continue
        references.append(f"- `{files.relative_path(summary_path)}` (primary)")
        if detail_path.is_file():
            references.append(f"- `{files.relative_path(detail_path)}` (additional detail)")

    if not references:
        return ""

    return "\n".join([
        "Research handoff (read before new exploration):",
        *references,
    ])


def build_architect_prompt(files: RuntimeFiles) -> str:
    return _render_template(
        _load_template(
        "agents",
        "architect",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "architect_preference_proposal_file": files.relative_path(files.architect_preference_proposal),
    })


def build_product_manager_prompt(files: RuntimeFiles) -> str:
    return _render_template(
        _load_template(
        "agents",
        "product-manager",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "pm_preference_proposal_file": files.relative_path(files.pm_preference_proposal),
    })


def build_reviewer_prompt(files: RuntimeFiles, is_review: bool = False) -> str:
    if is_review:
        return _render_template(
            _load_template(
            "commands",
            "review",
            project_dir=files.project_dir,
        ), {"feature_dir": files.feature_dir})
    return _render_template(
        _load_template(
        "agents",
        "reviewer",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "reviewer_preference_proposal_file": files.relative_path(files.reviewer_preference_proposal),
    })


def build_coder_prompt(files: RuntimeFiles) -> str:
    completion_marker = files.relative_path(files.implementation_dir / "done_1")
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"create the completion marker file `{completion_marker}` in the session directory "
        "and leave it empty. This must be the very last action you take."
    )
    completion_constraints = "\n".join([
        "- Do not update state.json from the coder step.",
        "- Do not write anything to the marker file; create it as an empty file.",
    ])
    return _render_template(
        _load_template(
        "agents",
        "coder",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "plan_file": files.relative_path(files.plan),
        "research_handoff": _build_coder_research_handoff(files),
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
    return _render_template(
        _load_template(
        "agents",
        "designer",
        project_dir=files.project_dir,
    ), {
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
    completion_marker = files.relative_path(files.implementation_dir / marker_name)
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"create the completion marker file `{completion_marker}` in the session directory "
        "and leave it empty. This must be the very last action you take."
    )
    completion_constraints = "\n".join([
        "- Do not update state.json in parallel coder mode.",
        "- Do not write anything to the marker file; create it as an empty file.",
    ])
    return _render_template(
        _load_template(
        "agents",
        "coder",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "plan_file": files.relative_path(subplan_path),
        "research_handoff": _build_coder_research_handoff(files),
        "completion_instruction": completion_instruction,
        "completion_constraints": completion_constraints,
    })


def build_fix_prompt(files: RuntimeFiles) -> str:
    return _render_template(
        _load_template(
        "commands",
        "fix",
        project_dir=files.project_dir,
    ), {
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

    return _render_template(
        _load_template(
        "commands",
        "confirmation",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "changed_files": changed_files,
        "reviewer_preference_proposal_file": files.relative_path(files.reviewer_preference_proposal),
    })


def build_code_researcher_prompt(topic: str, files: RuntimeFiles) -> str:
    return _render_template(
        _load_template(
        "agents",
        "code-researcher",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "topic": topic,
    })


def build_web_researcher_prompt(topic: str, files: RuntimeFiles) -> str:
    return _render_template(
        _load_template(
        "agents",
        "web-researcher",
        project_dir=files.project_dir,
    ), {
        "feature_dir": files.feature_dir,
        "project_dir": files.project_dir,
        "topic": topic,
    })


def build_initial_prompts(files: RuntimeFiles) -> dict[str, Path]:
    """Build startup prompts and return their file paths."""
    return {
        "architect": write_prompt_file(
            files.feature_dir,
            files.relative_path(files.planning_dir / "architect_prompt.md"),
            build_architect_prompt(files),
        ),
    }


def build_change_prompt(files: RuntimeFiles) -> str:
    return _render_template(
        _load_template(
        "commands",
        "change",
        project_dir=files.project_dir,
    ), {"feature_dir": files.feature_dir})
