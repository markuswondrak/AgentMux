from __future__ import annotations

import json
import re
from pathlib import Path

from ..shared.models import PreferenceProposal, RuntimeFiles

_BULLET_PREFIX = re.compile(r"^[-*+]\s*")
_BULLET_LINE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
_WHITESPACE = re.compile(r"\s+")


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


def proposal_artifact_for_source(files: RuntimeFiles, source_role: str) -> Path:
    if source_role == "product-manager":
        return files.pm_preference_proposal
    if source_role == "architect":
        return files.architect_preference_proposal
    if source_role == "reviewer":
        return files.reviewer_preference_proposal
    raise ValueError("source_role must be one of: product-manager, architect, reviewer.")


def load_preference_proposal(path: Path) -> PreferenceProposal | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Preference proposal file is not valid JSON: {path}") from exc
    return PreferenceProposal.from_dict(payload)


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


def _append_markdown_bullets(path: Path, bullets: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    text = existing_text
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text += "\n"
    text += "\n".join(bullets) + "\n"

    path.write_text(text, encoding="utf-8")


def apply_preference_proposal(project_dir: Path, proposal: PreferenceProposal) -> dict[str, list[str]]:
    prompts_root = project_dir / ".agentmux" / "prompts" / "agents"

    deduped_by_role: dict[str, list[str]] = {}
    seen_in_batch: dict[str, set[str]] = {}
    for entry in proposal.approved:
        normalized = normalize_preference_bullet(entry.bullet)
        if not normalized:
            continue
        role_seen = seen_in_batch.setdefault(entry.target_role, set())
        if normalized in role_seen:
            continue
        role_seen.add(normalized)
        deduped_by_role.setdefault(entry.target_role, []).append(entry.bullet)

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
        _append_markdown_bullets(path, append_block)
        appended_by_role[role] = append_block

    return appended_by_role
