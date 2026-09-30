"""Tests for the packaged application's graceful process controls."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api_server import app
from tests.router_test_support import override_context


@pytest.fixture(autouse=True)
def clear_process_controls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AQA_PACKAGED_MODE", raising=False)
    for name in ("shutdown_callback", "quit_token"):
        try:
            delattr(app.state, name)
        except (AttributeError, KeyError):
            pass
    yield
    for name in ("shutdown_callback", "quit_token"):
        try:
            delattr(app.state, name)
        except (AttributeError, KeyError):
            pass


def test_application_status_hides_quit_outside_packaged_mode() -> None:
    app.state.shutdown_callback = MagicMock()
    app.state.quit_token = "secret"

    response = TestClient(app).get("/api/application/status")

    assert response.status_code == 200
    assert response.json() == {
        "can_quit": False,
        "quit_token": None,
    }


def test_application_status_exposes_the_packaged_shutdown_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    app.state.shutdown_callback = MagicMock()
    app.state.quit_token = "secret"

    response = TestClient(app).get("/api/application/status")

    assert response.status_code == 200
    assert response.json() == {
        "can_quit": True,
        "quit_token": "secret",
    }


def test_quit_rejects_non_packaged_server(monkeypatch: pytest.MonkeyPatch) -> None:
    app.state.shutdown_callback = MagicMock()
    app.state.quit_token = "secret"

    response = TestClient(app).post(
        "/api/application/quit",
        headers={"X-AQA-Action": "secret"},
    )

    assert response.status_code == 404


def test_quit_rejects_invalid_confirmation_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    app.state.shutdown_callback = MagicMock()
    app.state.quit_token = "secret"

    response = TestClient(app).post(
        "/api/application/quit",
        headers={"X-AQA-Action": "wrong"},
    )

    assert response.status_code == 403
    app.state.shutdown_callback.assert_not_called()


def test_quit_cancels_generation_then_requests_graceful_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AQA_PACKAGED_MODE", "1")
    shutdown = MagicMock()
    context = MagicMock()
    app.state.shutdown_callback = shutdown
    app.state.quit_token = "secret"

    with override_context(app, context):
        response = TestClient(app).post(
            "/api/application/quit",
            headers={"X-AQA-Action": "secret"},
        )

    assert response.status_code == 202
    assert response.json() == {"status": "shutting_down"}
    context.discussion.cancel_active_generation.assert_called_once_with()
    shutdown.assert_called_once_with()
