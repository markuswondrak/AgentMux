from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..shared.models import ProjectPaths, RuntimeFiles, tasks_file_for_plan
from .execution_plan import load_execution_plan

if TYPE_CHECKING:
    from ..shared.models import AgentConfig

# Maps provider/CLI names to their native user-input tool name.
USER_ASK_TOOLS: dict[str, str] = {
    "claude": "AskUserQuestion",
    "opencode": "question",
    "gemini": "ask_user",
    "copilot": "ask_user",
}

_USER_ASK_FALLBACK = "your native ask / question tool"

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SHARED_FRAGMENT_PATTERN = re.compile(r"\[\[shared:([a-z0-9][a-z0-9_-]*)\]\]")
_SHARED_FRAGMENT_VARIANT_PATTERN = re.compile(r"\[\[shared:([a-z0-9][a-z0-9_-]*)\]\]")
_VALUE_PLACEHOLDER_PATTERN = re.compile(r"\[\[placeholder:([a-z0-9][a-z0-9_-]*)\]\]")
_SESSION_INCLUDE_PATTERN = re.compile(r"\[\[include:([^\]]+)\]\]")
_SESSION_INCLUDE_OPTIONAL_PATTERN = re.compile(r"\[\[include-optional:([^\]]+)\]\]")
_MAX_SHARED_FRAGMENT_EXPANSION_DEPTH = 8
_PROJECT_INSTRUCTIONS_PLACEHOLDER = "[[placeholder:project_instructions]]"


def _user_ask_tool_for(agent: AgentConfig | None) -> str:
    """Return the provider-native user-input tool name for the given agent.

    Falls back to a plain-text description when the agent's CLI is not
    in the mapping (e.g. codex) or when no agent is provided.
    """
    if agent is None:
        return _USER_ASK_FALLBACK
    key = agent.provider or agent.cli
    return USER_ASK_TOOLS.get(key, _USER_ASK_FALLBACK)


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


def _build_research_handoff(files: RuntimeFiles) -> str:
    """Build a research handoff section from completed research tasks.

    Uses state.json as the source of truth for completion status (the
    submit_research_done MCP tool writes events there rather than creating
    physical 'done' marker files).
    """
    research_dir = files.research_dir
    if not research_dir.is_dir():
        return ""

    # Read completed tasks from state.json
    state_file = files.feature_dir / "state.json"
    if not state_file.exists():
        return ""

    state = json.loads(state_file.read_text(encoding="utf-8"))
    done_code_tasks = {
        k for k, v in state.get("research_tasks", {}).items() if v == "done"
    }
    done_web_tasks = {
        k for k, v in state.get("web_research_tasks", {}).items() if v == "done"
    }

    references: list[str] = []
    for topic_dir in sorted(path for path in research_dir.iterdir() if path.is_dir()):
        summary_path = topic_dir / "summary.md"
        detail_path = topic_dir / "detail.md"

        # Determine completion from state based on topic prefix
        topic = topic_dir.name
        is_done = False
        if (
            topic.startswith("code-")
            and topic[5:] in done_code_tasks
            or topic.startswith("web-")
            and topic[4:] in done_web_tasks
        ):
            is_done = True

        if not is_done or not summary_path.is_file():
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


def build_architect_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
    rendered = _render_template(
        _load_template(
            "agents",
            "architect",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "user_ask_tool": _user_ask_tool_for(agent),
            "research_handoff": _build_research_handoff(files),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_product_manager_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
    rendered = _render_template(
        _load_template(
            "agents",
            "product-manager",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "user_ask_tool": _user_ask_tool_for(agent),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_prompt(
    files: RuntimeFiles, is_review: bool = False, agent: AgentConfig | None = None
) -> str:
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
            "user_ask_tool": _user_ask_tool_for(agent),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_logic_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
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
            "user_ask_tool": _user_ask_tool_for(agent),
            "review_role": "reviewer_logic",
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_quality_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
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
            "user_ask_tool": _user_ask_tool_for(agent),
            "review_role": "reviewer_quality",
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_expert_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
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
            "user_ask_tool": _user_ask_tool_for(agent),
            "review_role": "reviewer_expert",
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_followup_prompt(
    files: RuntimeFiles,
    pane_role: str,
    fix_request_rel: str,
    review_iteration: int,
    agent: AgentConfig | None = None,
) -> str:
    """Build a compact follow-up prompt for a reviewer after a fix iteration.

    Unlike `build_reviewer_<role>_prompt`, this deliberately omits the big
    initial includes (context.md, architecture.md, plan.md). It only references
    the aggregated fix_request so the reviewer can focus on whether their prior
    findings (still in session context) were resolved.
    """
    del agent  # reserved for future per-agent tweaks; unused today
    rendered = _render_template(
        _load_template(
            "commands",
            "review_followup",
            project_dir=files.project_dir,
        ),
        {
            "review_role": pane_role,
            "review_iteration": str(review_iteration),
            "fix_request_file": fix_request_rel,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_reviewer_summary_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
    """Build prompt asking the reviewer to write the implementation summary."""
    rendered = _render_template(
        _load_template(
            "commands",
            "summary",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_designer_prompt(files: RuntimeFiles) -> str:
    completion_instruction = (
        "FINAL STEP ONLY — after writing design.md and any optional design artifacts, "
        "stop. This must be the very last action you take."
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
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_coder_subplan_prompt(
    files: RuntimeFiles,
    subplan_path: Path,
    subplan_index: int,
) -> str:
    completion_instruction = (
        "FINAL STEP ONLY — once all code is written and nothing else remains, "
        f"call `mcp__agentmux__submit_done(subplan_index={subplan_index})` "
        "to signal completion to the orchestrator and materialize "
        f"`06_implementation/done_{subplan_index}`. "
        "This must be the very last action you take."
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

    plan_file_rel = files.relative_path(subplan_path)
    tasks_file_rel = tasks_file_relative

    plans_section = (
        f'<file path="{plan_file_rel}">\n'
        f"[[include:{plan_file_rel}]]\n"
        "</file>\n\n"
        f'<file path="{tasks_file_rel}">\n'
        f"[[include:{tasks_file_rel}]]\n"
        "</file>"
    )
    post_discipline_items = (
        f"12. If implementation reveals that requirements or the plan need adjustment "
        "(e.g. a requirement turns out to be infeasible as written, or a task needs "
        "to be split or reordered), "
        f"update `requirements.md` and `{plan_file_rel}` / `{tasks_file_rel}` "
        "accordingly so they stay in sync with reality.\n"
        f"13. {completion_instruction}"
    )

    rendered = _render_template(
        _load_template(
            "agents",
            "coder",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "plans_section": plans_section,
            "research_handoff": _build_research_handoff(files),
            "post_discipline_items": post_discipline_items,
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_coder_whole_plan_prompt(
    files: RuntimeFiles, agent: AgentConfig | None = None
) -> str:
    """Build a single combined prompt for single-coder mode (e.g. copilot).

    Reads all sub-plans from execution_plan.yaml and embeds their content
    inline so one coder instance can implement the full plan using internal
    sub-agents.  The coder is instructed to write each done_N marker as it
    finishes the corresponding plan.

    When ``agent.sub_agent_tool`` is set, item 14 instructs parallel sub-agent
    work via that tool; otherwise it describes sequential delegation.
    """
    execution_plan = load_execution_plan(files.planning_dir)

    plans_blocks: list[str] = []
    all_marker_indexes: list[int] = []

    for group in execution_plan.groups:
        for plan_ref in group.plans:
            match = re.match(r"^plan_(\d+)\.md$", plan_ref.file)
            if match is None:
                raise RuntimeError(
                    f"Unexpected plan file name in execution_plan.yaml: {plan_ref.file}"
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
                    f"**Signal completion for plan {index}**: "
                    f"call `mcp__agentmux__submit_done(subplan_index={index})` "
                    f"when this plan is fully implemented and validated. "
                    f"This materializes `06_implementation/done_{index}`.",
                    "",
                ]
            )
            plans_blocks.append(block)

    plans_content = "\n".join(plans_blocks)

    all_marker_indexes_sorted = sorted(all_marker_indexes)
    done_calls = [
        f"`mcp__agentmux__submit_done(subplan_index={i})`"
        for i in all_marker_indexes_sorted
    ]
    done_calls_str = ", ".join(done_calls)

    completion_instruction = (
        "FINAL STEP — once all code is written and all validations pass "
        "for every plan above, call the completion tool for each plan: "
        f"{done_calls_str}. "
        "You may call submit_done as you finish each individual plan, "
        "or all at once at the end. "
        "Each call signals to the orchestrator that the corresponding plan is complete."
    )

    sequential_subagent_item = (
        "14. Sub-agent delegation: For each plan, spawn a dedicated sub-agent and "
        "delegate that plan's full implementation to it. The sub-agent works through "
        "the plan's task checklist end-to-end "
        "(TDD → implement → validate → check off). "
        "Only move to the next plan once the sub-agent for the current plan has "
        "completed and its tasks are checked off."
    )
    if agent is not None and agent.sub_agent_tool:
        tool = agent.sub_agent_tool
        subagent_item_14 = (
            f"14. Sub-agent delegation: For each plan, use the `/{tool}` command "
            "to spawn a dedicated sub-agent and delegate that plan's full "
            "implementation to it. You may run multiple plans in parallel — each "
            "sub-agent should work through its plan's task checklist end-to-end "
            "(TDD → implement → validate → check off). "
            "Do not wait for one plan to finish before starting another unless "
            "your environment requires it."
        )
    else:
        subagent_item_14 = sequential_subagent_item

    post_discipline_items = (
        "12. If implementation reveals that requirements or a plan need adjustment "
        "(e.g. a requirement turns out to be infeasible as written, or tasks need "
        "reordering), update `requirements.md` and the embedded plan's task list "
        "accordingly so they stay in sync with reality.\n"
        f"13. {completion_instruction}\n"
        f"{subagent_item_14}"
    )

    rendered = _render_template(
        _load_template(
            "agents",
            "coder",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "project_dir": files.project_dir,
            "plans_section": plans_content,
            "research_handoff": _build_research_handoff(files),
            "post_discipline_items": post_discipline_items,
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
    """Build startup prompts and return their file paths.

    Intentionally empty: ArchitectingHandler.enter() creates and dispatches
    architect_prompt.md when the architecting phase is entered. Pre-creating
    files here would cause seed_existing_files() to emit a file.created event
    before any agent has run, triggering PlanningHandler.enter() while
    architecture.md is still absent.
    """
    return {}


def build_change_prompt(files: RuntimeFiles, agent: AgentConfig | None = None) -> str:
    rendered = _render_template(
        _load_template(
            "commands",
            "change",
            project_dir=files.project_dir,
        ),
        {
            "feature_dir": files.feature_dir,
            "user_ask_tool": _user_ask_tool_for(agent),
            "research_handoff": _build_research_handoff(files),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)


def build_planner_prompt(files: RuntimeFiles, agent: AgentConfig | None = None) -> str:
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
            "user_ask_tool": _user_ask_tool_for(agent),
            "research_handoff": _build_research_handoff(files),
        },
    )
    return _expand_session_includes(rendered, files.feature_dir)
