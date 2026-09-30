"""Small transport errors shared by independently imported route modules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int,
    code: str,
    detail: str,
    *,
    params: Mapping[str, Any] | None = None,
) -> HTTPException:
    """Build an HTTP error with stable UI metadata."""

    exception = HTTPException(status_code=status_code, detail=detail)
    exception.error_code = code
    exception.error_params = dict(params or {})
    return exception
