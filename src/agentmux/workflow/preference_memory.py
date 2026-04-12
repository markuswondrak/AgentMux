from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..shared.models import ProjectPaths

_BULLET_PREFIX = re.compile(r"^[-*+]\s*")
_BULLET_LINE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_WHITESPACE = re.compile(r"\s+")
_SECTION_HEADER = "## Approved Preferences"


def _strip_bullet_prefix(text: str) -> str:
    return _BULLET_PREFIX.sub("", text.strip(), count=1)


def normalize_preference_bullet(text: str) -> str:
    normalized = _WHITESPACE.sub(" ", _strip_bullet_prefix(text)).strip()
    return normalized.casefold()


def format_preference_bullet(text: str) -> str:
    content = _WHITESPACE.sub(" ", _strip_bullet_prefix(text)).strip()
    if not content:
        raise ValueError("Preference bullet text must not be empty.")
    return f"- {content}"


def _load_existing_normalized_bullets(path: Path) -> set[str]:
    if not path.is_file():
        return set()

    normalized: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = _BULLET_LINE.match(raw_line)
        if match is None:
            continue
        value = normalize_preference_bullet(match.group(1))
        if value:
            normalized.add(value)
    return normalized


def _append_to_preference_section(path: Path, bullets: list[str]) -> None:
    """Append bullets under the '## Approved Preferences' section.

    Creates the section at the end of the file if it does not exist yet.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if text and not text.endswith("\n"):
        text += "\n"

    if _SECTION_HEADER not in text:
        if text.strip():
            text += "\n"
        text += f"{_SECTION_HEADER}\n\n"

    text += "\n".join(bullets) + "\n"
    path.write_text(text, encoding="utf-8")


def apply_preference_entries(
    project_dir: Path,
    entries: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Write approved preference bullets directly to project-level custom prompt files.

    Each entry must have ``target_role`` (str) and ``bullet`` (str) keys.
    Bullets are deduplicated against existing content (case-insensitive).

    Returns a mapping of role -> list of newly appended formatted bullets.
    """
    paths = ProjectPaths.from_project(project_dir)
    prompts_root = paths.agent_prompts_dir

    deduped_by_role: dict[str, list[str]] = {}
    seen_in_batch: dict[str, set[str]] = {}
    for entry in entries:
        target_role = entry.get("target_role", "")
        bullet = entry.get("bullet", "")
        if not target_role or not bullet:
            continue
        normalized = normalize_preference_bullet(bullet)
        if not normalized:
            continue
        role_seen = seen_in_batch.setdefault(target_role, set())
        if normalized in role_seen:
            continue
        role_seen.add(normalized)
        deduped_by_role.setdefault(target_role, []).append(bullet)

    appended_by_role: dict[str, list[str]] = {}
    for role, bullets in deduped_by_role.items():
        path = prompts_root / f"{role}.md"
        existing = _load_existing_normalized_bullets(path)

        append_block: list[str] = []
        for bullet in bullets:
            normalized = normalize_preference_bullet(bullet)
            if normalized in existing:
                continue
            append_block.append(format_preference_bullet(bullet))
            existing.add(normalized)

        if not append_block:
            continue
        _append_to_preference_section(path, append_block)
        appended_by_role[role] = append_block

    return appended_by_role
