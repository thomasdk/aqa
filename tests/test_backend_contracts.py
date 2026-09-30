"""Focused backend contracts for shipped behavior."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api_server import app
from src.service.api_app import create_app
from src.service.discussion import DiscussionState
from src.service.routers.dependencies import get_context
from tests.router_test_support import override_context


def _registered_routes() -> list[object]:
    """Return concrete routes across eager and lazy FastAPI router versions."""

    routes: list[object] = []
    for route in app.routes:
        original_router = getattr(route, "original_router", None)
        if original_router is None:
            routes.append(route)
        else:
            routes.extend(original_router.routes)
    return routes


def test_removed_discussion_save_endpoint_returns_structured_404() -> None:

    context = MagicMock()
    with override_context(app, context):
        response = TestClient(app).post("/api/discussions/save")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    context.discussion.save_discussion.assert_not_called()


def test_create_app_uses_an_overridable_app_context_dependency() -> None:
    application = create_app()
    context = MagicMock()
    context.discussion.state = DiscussionState()
    context.discussion.has_active_discussion = False

    assert application.state.app_context is None
    application.dependency_overrides[get_context] = lambda: context
    try:
        response = TestClient(application).get("/api/discussions/state")
    finally:
        application.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "material": "",
        "initial_question": "",
        "messages": [],
        "has_errors": False,
        "round_number": 0,
        "round_status": None,
        "has_active_discussion": False,
    }
    assert application.state.app_context is None


@pytest.mark.parametrize(
    ("path", "module"),
    [
        ("/api/health", "src.service.routers.application"),
        ("/api/preview/templates", "src.service.routers.preview"),
        ("/api/defaults/material", "src.service.routers.defaults"),
        ("/api/sessions", "src.service.routers.sessions"),
    ],
)
def test_domain_routes_are_owned_by_independent_router_modules(
    path: str,
    module: str,
) -> None:

    matching = [route for route in _registered_routes() if getattr(route, "path", None) == path]
    assert len(matching) == 1
    assert matching[0].endpoint.__module__ == module
