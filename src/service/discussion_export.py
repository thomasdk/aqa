"""Discussion export coordination."""

from __future__ import annotations

from collections.abc import Callable

from src.service.discussion_storage import StoredDiscussion


def export_markdown(
    stored: StoredDiscussion | None,
    *,
    synchronize_rounds: Callable[[], None],
    prompt_documentation: Callable[[], list[tuple[str, str, str]]],
    locale: str,
) -> str | None:
    """Synchronize unsaved messages and render the public Markdown export."""

    if stored is None:
        return None
    synchronize_rounds()
    return stored.to_markdown(locale=locale, prompt_documentation=prompt_documentation())


__all__ = ["export_markdown"]
