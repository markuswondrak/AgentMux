from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..shared.models import ProjectPaths, RuntimeFiles, tasks_file_for_plan
from .execution_plan import load_execution_plan

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SHARED_FRAGMENT_PATTERN = re.compile(r"\[\[shared:([a-z0-9][a-z0-9_-]*)\]\]")
_VALUE_PLACEHOLDER_PATTERN = re.compile(r"\[\[placeholder:([a-z0-9][a-z0-9_-]*)\]\]")
_SESSION_INCLUDE_PATTERN = re.compile(r"\[\[include:([^\]]+)\]\]")
_SESSION_INCLUDE_OPTIONAL_PATTERN = re.compile(r"\[\[include-optional:([^\]]+)\]\]")
_MAX_SHARED_FRAGMENT_EXPANSION_DEPTH = 8
_PROJECT_INSTRUCTIONS_PLACEHOLDER = "[[placeholder:project_instructions]]"

_CHANGED_FILES_FALLBACK = "_Unable to read changed files from git status._"
_CONFIRMATION_APPROVAL_FIELDS: tuple[str, ...] = (
    "action",
    "exclude_files",
    "commit_message",
)


def confirmation_approval_payload_fields() -> tuple[str, ...]:
    return _CONFIRMATION_APPROVAL_FIELDS


def _append_confirmation_commit_message_contract(prompt: str) -> str:
    if "commit_message" in prompt:
        return prompt
    return "\n".join(
        [
            prompt.rstrip(),
            "",
            "Approval payload contract extension:",
            "- `commit_message` is optional and may contain a reviewer-authored "
            "summary for the final commit.",
            "",
        ]
    )


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
        paths = ProjectPaths.from_project(project_dir)
        project_prompt = paths.prompts_dir / subdir / f"{name}.md"
        if project_prompt.is_file():
            project_instructions = project_prompt.read_text(encoding="utf-8")
    return template.replace(_PROJECT_INSTRUCTIONS_PLACEHOLDER, project_instructions)


def _render_template(template: str, values: dict[str, object]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(key)
        return str(values[key])

    return _VALUE_PLACEHOLDER_PATTERN.sub(_replace, template)


def _expand_session_includes(template: str, feature_dir: Path) -> str:
    def _resolve_path(raw_path: str) -> Path:
        include_path = raw_path.strip()
        return feature_dir / include_path

    def _replace_optional(match: re.Match[str]) -> str:
        path = _resolve_path(match.group(1))
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def _replace_required(match: re.Match[str]) -> str:
        path = _resolve_path(match.group(1))
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    expanded = _SESSION_INCLUDE_OPTIONAL_PATTERN.sub(_replace_optional, template)
    return _SESSION_INCLUDE_PATTERN.sub(_replace_required, expanded)


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
            references.append(
                f"- `{files.relative_path(detail_path)}` (additional detail)"
            )

    if not references:
        return ""

    return "\n".join(
        [
            "Research handoff (read before new exploration):",
            *references,
        ]
    )


def build_architect_prompt(files: RuntimeFiles) -> str:
    rendered = _render_template(
        _load_template(
            "agents",
            "architect",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "architect_preference_proposal_file": files.relative_path(
                files.architect_preference_proposal
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_product_manager_prompt(files: RuntimeFiles) -> str:
    rendered = _render_template(
        _load_template(
            "agents",
            "product-manager",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "pm_preference_proposal_file": files.relative_path(
                files.pm_preference_proposal
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_prompt(files: RuntimeFiles, is_review: bool = False) -> str:
    if is_review:
        rendered = _render_template(
            _load_template(
                "commands",
                "review",
                project_dir=files.project_dir,
            ),
            {"feature_dir": files.feature_dir},
        )
        return _expand_session_includes(rendered, files.feature_dir)
    rendered = _render_template(
        _load_template(
            "agents",
            "reviewer",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "reviewer_preference_proposal_file": files.relative_path(
                files.reviewer_preference_proposal
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_logic_prompt(files: RuntimeFiles) -> str:
    """Build prompt for Logic & Alignment reviewer."""
    rendered = _render_template(
        _load_template(
            "agents",
            "reviewer_logic",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "reviewer_preference_proposal_file": files.relative_path(
                files.reviewer_preference_proposal
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_quality_prompt(files: RuntimeFiles) -> str:
    """Build prompt for Quality & Style reviewer."""
    rendered = _render_template(
        _load_template(
            "agents",
            "reviewer_quality",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "reviewer_preference_proposal_file": files.relative_path(
                files.reviewer_preference_proposal
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_expert_prompt(files: RuntimeFiles) -> str:
    """Build prompt for Deep-Dive Expert reviewer."""
    rendered = _render_template(
        _load_template(
            "agents",
            "reviewer_expert",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "reviewer_preference_proposal_file": files.relative_path(
                files.reviewer_preference_proposal
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_designer_prompt(files: RuntimeFiles) -> str:
    completion_instruction = (
        "FINAL STEP ONLY — after writing design.md and any optional design artifacts, "
        "stop. Do not update state.json or any workflow status from the designer step."
    )
    completion_constraints = "\n".join(
        [
            "- Do not update state.json from the designer step.",
            "- `design.md` is the completion signal for this phase.",
        ]
    )
    rendered = _render_template(
        _load_template(
            "agents",
            "designer",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "completion_instruction": completion_instruction,
            "completion_constraints": completion_constraints,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_coder_subplan_prompt(
    files: RuntimeFiles,
    subplan_path: Path,
    subplan_index: int,
) -> str:
    marker_name = f"done_{subplan_index}"
    completion_marker = files.relative_path(files.implementation_dir / marker_name)
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"create the completion marker file `{completion_marker}` "
        "in the session directory and leave it empty. "
        "This must be the very last action you take."
    )
    completion_constraints = "\n".join(
        [
            "- Do not update state.json in parallel coder mode.",
            "- Do not write anything to the marker file; create it as an empty file.",
        ]
    )

    # Compute per-plan tasks file path and validate it exists
    tasks_path = tasks_file_for_plan(files.planning_dir, subplan_index)
    if not tasks_path.is_file():
        raise FileNotFoundError(
            f"Per-plan tasks file not found: {tasks_path}. "
            f"The architect must create tasks_{subplan_index}.md "
            f"alongside plan_{subplan_index}.md."
        )
    tasks_file_relative = files.relative_path(tasks_path)

    rendered = _render_template(
        _load_template(
            "agents",
            "coder",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "plan_file": files.relative_path(subplan_path),
            "tasks_file": tasks_file_relative,
            "research_handoff": _build_coder_research_handoff(files),
            "completion_instruction": completion_instruction,
            "completion_constraints": completion_constraints,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_coder_whole_plan_prompt(files: RuntimeFiles) -> str:
    """Build a single combined prompt for single-coder mode (e.g. copilot).

    Reads all sub-plans from execution_plan.json and embeds their content
    inline so one coder instance can implement the full plan using internal
    sub-agents.  The coder is instructed to write each done_N marker as it
    finishes the corresponding plan.
    """
    execution_plan = load_execution_plan(files.planning_dir)

    plans_blocks: list[str] = []
    all_marker_indexes: list[int] = []

    for group in execution_plan.groups:
        for plan_ref in group.plans:
            match = re.match(r"^plan_(\d+)\.md$", plan_ref.file)
            if match is None:
                raise RuntimeError(
                    f"Unexpected plan file name in execution_plan.json: {plan_ref.file}"
                )
            index = int(match.group(1))
            all_marker_indexes.append(index)

            plan_path = files.planning_dir / plan_ref.file
            tasks_path = tasks_file_for_plan(files.planning_dir, index)

            if not plan_path.is_file():
                raise FileNotFoundError(f"Plan file not found: {plan_path}")
            if not tasks_path.is_file():
                raise FileNotFoundError(
                    f"Per-plan tasks file not found: {tasks_path}. "
                    f"The planner must create tasks_{index}.md "
                    f"alongside plan_{index}.md."
                )

            plan_rel = files.relative_path(plan_path)
            tasks_rel = files.relative_path(tasks_path)
            done_rel = files.relative_path(files.implementation_dir / f"done_{index}")

            block = "\n".join(
                [
                    f"### Plan {index}: `{plan_rel}`",
                    "",
                    plan_path.read_text(encoding="utf-8").strip(),
                    "",
                    f"#### Task checklist for plan {index}: `{tasks_rel}`",
                    "",
                    tasks_path.read_text(encoding="utf-8").strip(),
                    "",
                    f"**Completion marker for plan {index}**: "
                    f"create empty file `{done_rel}` when this plan is "
                    f"fully implemented and validated.",
                    "",
                ]
            )
            plans_blocks.append(block)

    plans_content = "\n".join(plans_blocks)

    all_marker_indexes_sorted = sorted(all_marker_indexes)
    all_markers = [
        f"`{files.relative_path(files.implementation_dir / f'done_{i}')}`"
        for i in all_marker_indexes_sorted
    ]
    markers_str = ", ".join(all_markers)

    completion_instruction = (
        "FINAL STEP — once all code is written and all validations pass "
        "for every plan above, ensure these completion marker files exist "
        f"(each as an empty file): {markers_str}. "
        "You may create each marker as you finish each individual plan, "
        "or all at once at the end. "
        "Do not write anything to the marker files — they must be empty."
    )
    completion_constraints = "\n".join(
        [
            "- Do not update state.json.",
            "- Do not write anything to the marker files; create them as empty files.",
        ]
    )

    rendered = _render_template(
        _load_template(
            "agents",
            "coder_whole_plan",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "plans_content": plans_content,
            "research_handoff": _build_coder_research_handoff(files),
            "completion_instruction": completion_instruction,
            "completion_constraints": completion_constraints,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_fix_prompt(files: RuntimeFiles) -> str:
    rendered = _render_template(
        _load_template(
            "commands",
            "fix",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


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

    rendered = _render_template(
        _load_template(
            "commands",
            "confirmation",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "changed_files": changed_files,
            "reviewer_preference_proposal_file": files.relative_path(
                files.reviewer_preference_proposal
            ),
        },
    )
    prompt = _expand_session_includes(rendered, files.feature_dir)
    return _append_confirmation_commit_message_contract(prompt)


def build_code_researcher_prompt(topic: str, files: RuntimeFiles) -> str:
    rendered = _render_template(
        _load_template(
            "agents",
            "code-researcher",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "topic": topic,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_web_researcher_prompt(topic: str, files: RuntimeFiles) -> str:
    rendered = _render_template(
        _load_template(
            "agents",
            "web-researcher",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "topic": topic,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


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
    rendered = _render_template(
        _load_template(
            "commands",
            "change",
            project_dir=files.project_dir,
        ),
        {"feature_dir": files.feature_dir},
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_planner_prompt(files: RuntimeFiles) -> str:
    """Build prompt for planner agent.

    The planner receives the architecture document and creates execution plans.
    """
    rendered = _render_template(
        _load_template(
            "agents",
            "planner",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "planner_preference_proposal_file": files.relative_path(
                files.planning_dir / "approved_preferences.json"
            ),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)
