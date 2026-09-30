"""Pure material formatting and discussion-title utilities."""

from __future__ import annotations

import re
from datetime import datetime

MATERIAL_TYPES = {
    "interview": "Interview",
    "focus_group": "Focus Group",
    "document": "Text Document",
    "media": "Multimedia Transcript",
    "fieldnotes": "Field Notes",
    "memo": "Research Memo",
    "other": "Other",
}

LINE_NUMBERED_MATERIAL_TYPES = set(MATERIAL_TYPES)
DEFAULT_TITLE_EXCERPT_MAX_CHARS = 80
DEFAULT_TITLE_FALLBACK = "Discussion"


def is_line_numbered_material(text: str) -> bool:
    """Return whether the first nonblank line has the stable citation prefix."""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return bool(re.match(r"^Z\d{4,}:", stripped))
    return False


def add_line_numbers_to_material(text: str, *, start_line: int = 1) -> str:
    """Add stable physical-line references used for LLM citations.

    Each nonblank source line is one citation unit, regardless of punctuation.
    Blank source lines remain paragraph spacing and do not consume a reference.
    Long lines wrap only in the UI, never in this formatter.
    """

    if not text or is_line_numbered_material(text):
        return text

    source_lines = text.splitlines()
    if not source_lines:
        return text

    safe_start = max(1, int(start_line))
    reference_count = sum(bool(line.strip()) for line in source_lines)
    if not reference_count:
        return "\n".join("" for _ in source_lines)

    width = max(4, len(str(safe_start + reference_count - 1)))
    next_reference = safe_start
    output: list[str] = []
    for line in source_lines:
        if not line.strip():
            output.append("")
            continue
        output.append(f"Z{next_reference:0{width}d}: {line}")
        next_reference += 1
    return "\n".join(output)


def material_type_uses_line_numbers(material_type: str) -> bool:
    """Return whether material of this type receives citation line numbers."""

    return material_type in LINE_NUMBERED_MATERIAL_TYPES


def generate_default_discussion_title(
    timestamp: datetime,
    material: str,
) -> str:
    """Build the stable ``YYYY-MM-DD HH:MM <excerpt>`` default title."""

    cleaned = " ".join((material or "").split()).strip()
    excerpt = (
        cleaned[:DEFAULT_TITLE_EXCERPT_MAX_CHARS].rstrip() if cleaned else DEFAULT_TITLE_FALLBACK
    )
    return f"{timestamp.strftime('%Y-%m-%d %H:%M')} {excerpt}"


__all__ = [
    "DEFAULT_TITLE_EXCERPT_MAX_CHARS",
    "DEFAULT_TITLE_FALLBACK",
    "LINE_NUMBERED_MATERIAL_TYPES",
    "MATERIAL_TYPES",
    "add_line_numbers_to_material",
    "generate_default_discussion_title",
    "is_line_numbered_material",
    "material_type_uses_line_numbers",
]
