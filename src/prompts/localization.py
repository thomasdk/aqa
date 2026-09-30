"""Locale-tag normalization for prompt metadata."""

from __future__ import annotations

import re

_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def normalize_locale(value: str | None) -> str:
    """Return a predictable BCP-47-ish locale tag or the empty string.

    We intentionally support the practical subset used by the product.  A
    malformed tag is ignored rather than becoming a persistence key.
    """

    raw = (value or "").strip().replace("_", "-")
    if not raw or not _LOCALE_RE.match(raw):
        return ""
    parts = raw.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.upper() if len(part) == 2 and part.isalpha() else part.lower())
    return "-".join(normalized)


__all__ = ["normalize_locale"]
