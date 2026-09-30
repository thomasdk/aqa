"""Shared FastAPI dependencies for route modules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from src.service.context import AppContext


def get_context(request: Request) -> AppContext:
    """Return the context owned by the application serving this request."""

    context = getattr(request.app.state, "app_context", None)
    if context is not None:
        return context

    factory = getattr(request.app.state, "app_context_factory", None)
    lock = getattr(request.app.state, "app_context_lock", None)
    if not callable(factory) or lock is None:
        raise RuntimeError("FastAPI application context is not configured")

    with lock:
        context = getattr(request.app.state, "app_context", None)
        if context is None:
            context = factory()
            request.app.state.app_context = context
    return context


ContextDependency = Annotated[AppContext, Depends(get_context)]


__all__ = [
    "ContextDependency",
    "get_context",
]
