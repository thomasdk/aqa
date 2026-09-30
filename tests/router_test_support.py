"""Shared FastAPI dependency overrides for router tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI

from src.service.routers.dependencies import get_context

_MISSING = object()


@contextmanager
def override_context(application: FastAPI, context: Any) -> Iterator[None]:
    """Temporarily supply a test context through the public router dependency."""

    previous = application.dependency_overrides.get(get_context, _MISSING)
    application.dependency_overrides[get_context] = lambda: context
    try:
        yield
    finally:
        if previous is _MISSING:
            del application.dependency_overrides[get_context]
        else:
            application.dependency_overrides[get_context] = previous
