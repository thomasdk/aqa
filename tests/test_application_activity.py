"""Contract tests for the privacy-safe application activity endpoint."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.service.activity import ApplicationActivity
from src.service.api_app import create_app
from src.service.routers.application import router as application_router


def _application() -> FastAPI:
    application = create_app()
    application.include_router(application_router)
    return application


def test_activity_endpoint_pages_events_in_order_and_enforces_limit() -> None:
    application = _application()
    feed = application.state.application_activity
    feed.clear()
    first = feed.record("server_started")
    second = feed.record("request_completed", params={"method": "GET", "route": "/api/hosts"})

    with TestClient(application) as client:
        response = client.get(f"/api/application/activity?after={first.sequence}&limit=1")
        invalid_limit = client.get("/api/application/activity?limit=0")

    assert response.status_code == 200
    assert response.json() == {
        "events": [
            {
                "sequence": second.sequence,
                "timestamp": second.timestamp,
                "level": "info",
                "code": "request_completed",
                "params": {"method": "GET", "route": "/api/hosts"},
            }
        ],
        "next_cursor": second.sequence,
        "truncated": False,
    }
    assert invalid_limit.status_code == 422


def test_activity_reports_truncation_after_500_event_ring_discards_history() -> None:
    feed = ApplicationActivity()
    for _ in range(501):
        last = feed.record("request_completed")

    events, next_cursor, truncated = feed.since(after=0, limit=500)

    assert len(events) == 500
    assert events[0]["sequence"] == 2
    assert next_cursor == 501
    assert truncated is True
    assert last.sequence == 501


def test_activity_records_only_safe_action_metadata_and_excludes_read_poll_noise() -> None:
    application = _application()

    @application.get("/api/activity-test/{opaque_value}")
    def completed_request(opaque_value: str) -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/activity-failure")
    def failed_request() -> None:
        raise RuntimeError("provider token=must-not-appear /private/path")

    @application.post("/api/activity-action")
    def action_request() -> dict[str, str]:
        return {"status": "ok"}

    feed = application.state.application_activity
    with TestClient(application, raise_server_exceptions=False) as client:
        feed.clear()
        cursor = feed.record("marker").sequence

        completed = client.get("/api/activity-test/secret-value?api_key=not-for-logs")
        action = client.post("/api/activity-action")
        rejected = client.get("/api/no-such-route/secret-value?token=not-for-logs")
        failed = client.get("/api/activity-failure")
        client.get("/api/health")
        client.get("/api/application/status")
        activity = client.get(f"/api/application/activity?after={cursor}")

    assert completed.status_code == 200
    assert action.status_code == 200
    assert rejected.status_code == 404
    assert failed.status_code == 500

    events = activity.json()["events"]
    assert [event["code"] for event in events] == [
        "request_completed",
        "http_rejection",
        "unexpected_failure",
    ]
    assert events[0]["params"] == {
        "method": "POST",
        "route": "/api/activity-action",
        "status": 200,
    }
    assert events[1]["params"] == {"method": "GET", "status": 404}
    assert events[2]["params"] == {
        "method": "GET",
        "route": "/api/activity-failure",
    }

    serialized = json.dumps(events)
    for forbidden in (
        "secret-value",
        "not-for-logs",
        "must-not-appear",
        "/private/path",
        "api_key",
        "token",
    ):
        assert forbidden not in serialized


def test_activity_records_server_lifecycle() -> None:
    application = _application()
    feed = application.state.application_activity

    with TestClient(application):
        pass

    events, _, _ = feed.since(after=0, limit=200)
    assert [event["code"] for event in events] == ["server_started", "server_stopped"]
