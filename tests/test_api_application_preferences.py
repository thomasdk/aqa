from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.service.api_app import create_app


def test_application_preferences_round_trip_without_exposing_settings(
    monkeypatch, tmp_path
) -> None:
    user_data = tmp_path / "user-data"
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(user_data))

    with TestClient(create_app()) as client:
        initial = client.get("/api/application/preferences")
        assert initial.status_code == 200
        assert initial.json() == {
            "ui_locale": "en",
            "appearance": "system",
            "ai_source": "integrated",
            "local_ai_context_tokens": 32_768,
            "local_ai_context_default_tokens": 32_768,
            "local_ai_mtp_enabled": False,
            "notifications_enabled": True,
            "notification_permission_auto_attempted": False,
            "prevent_sleep_while_generating": True,
            "last_active_discussion_id": None,
        }

        updated = client.put(
            "/api/application/preferences",
            json={
                "ui_locale": "de",
                "appearance": "dark",
                "ai_source": "external",
                "local_ai_context_tokens": 40_960,
                "local_ai_mtp_enabled": True,
                "notifications_enabled": False,
                "notification_permission_auto_attempted": True,
                "prevent_sleep_while_generating": False,
                "last_active_discussion_id": "session-123",
            },
        )
        assert updated.status_code == 200
        assert updated.json() == {
            "ui_locale": "de",
            "appearance": "dark",
            "ai_source": "external",
            "local_ai_context_tokens": 40_960,
            "local_ai_context_default_tokens": 32_768,
            "local_ai_mtp_enabled": True,
            "notifications_enabled": False,
            "notification_permission_auto_attempted": True,
            "prevent_sleep_while_generating": False,
            "last_active_discussion_id": "session-123",
        }

    persisted = json.loads((user_data / "settings.json").read_text(encoding="utf-8"))
    assert persisted["ui_locale"] == "de"
    assert persisted["appearance"] == "dark"
    assert persisted["ai_source"] == "external"
    assert persisted["local_ai_context_tokens"] == 40_960
    assert persisted["local_ai_mtp_enabled"] is True
    assert persisted["notifications_enabled"] is False
    assert persisted["notification_permission_auto_attempted"] is True
    assert persisted["prevent_sleep_while_generating"] is False
    assert persisted["last_active_discussion_id"] == "session-123"
    assert set(initial.json()) == {
        "ui_locale",
        "appearance",
        "ai_source",
        "local_ai_context_tokens",
        "local_ai_context_default_tokens",
        "local_ai_mtp_enabled",
        "notifications_enabled",
        "notification_permission_auto_attempted",
        "prevent_sleep_while_generating",
        "last_active_discussion_id",
    }

    with TestClient(create_app()) as restarted_client:
        assert restarted_client.get("/api/application/preferences").json() == {
            "ui_locale": "de",
            "appearance": "dark",
            "ai_source": "external",
            "local_ai_context_tokens": 40_960,
            "local_ai_context_default_tokens": 32_768,
            "local_ai_mtp_enabled": True,
            "notifications_enabled": False,
            "notification_permission_auto_attempted": True,
            "prevent_sleep_while_generating": False,
            "last_active_discussion_id": "session-123",
        }


def test_application_preferences_accept_partial_updates_and_validate_values(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(tmp_path / "user-data"))

    with TestClient(create_app()) as client:
        assert client.put("/api/application/preferences", json={"ui_locale": "de"}).json() == {
            "ui_locale": "de",
            "appearance": "system",
            "ai_source": "integrated",
            "local_ai_context_tokens": 32_768,
            "local_ai_context_default_tokens": 32_768,
            "local_ai_mtp_enabled": False,
            "notifications_enabled": True,
            "notification_permission_auto_attempted": False,
            "prevent_sleep_while_generating": True,
            "last_active_discussion_id": None,
        }
        assert client.put(
            "/api/application/preferences", json={"ai_source": "external"}
        ).json() == {
            "ui_locale": "de",
            "appearance": "system",
            "ai_source": "external",
            "local_ai_context_tokens": 32_768,
            "local_ai_context_default_tokens": 32_768,
            "local_ai_mtp_enabled": False,
            "notifications_enabled": True,
            "notification_permission_auto_attempted": False,
            "prevent_sleep_while_generating": True,
            "last_active_discussion_id": None,
        }
        assert client.put(
            "/api/application/preferences",
            json={"local_ai_context_tokens": 40_960, "local_ai_mtp_enabled": True},
        ).json() == {
            "ui_locale": "de",
            "appearance": "system",
            "ai_source": "external",
            "local_ai_context_tokens": 40_960,
            "local_ai_context_default_tokens": 32_768,
            "local_ai_mtp_enabled": True,
            "notifications_enabled": True,
            "notification_permission_auto_attempted": False,
            "prevent_sleep_while_generating": True,
            "last_active_discussion_id": None,
        }
        assert (
            client.put(
                "/api/application/preferences", json={"notifications_enabled": False}
            ).json()["notifications_enabled"]
            is False
        )
        assert (
            client.put(
                "/api/application/preferences",
                json={"prevent_sleep_while_generating": False},
            ).json()["prevent_sleep_while_generating"]
            is False
        )
        assert (
            client.put(
                "/api/application/preferences",
                json={"last_active_discussion_id": "session-456"},
            ).json()["last_active_discussion_id"]
            == "session-456"
        )
        assert (
            client.put(
                "/api/application/preferences",
                json={"last_active_discussion_id": None},
            ).json()["last_active_discussion_id"]
            is None
        )
        assert (
            client.put(
                "/api/application/preferences", json={"ui_locale": "unsupported"}
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/application/preferences", json={"local_ai_context_tokens": 40_000}
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/application/preferences",
                json={
                    "local_ai_context_tokens": 262_144,
                    "local_ai_context_model_id": "gemma-4-e2b",
                },
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/application/preferences",
                json={
                    "local_ai_context_tokens": 262_144,
                    "local_ai_context_model_id": "gemma-4-12b",
                },
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/api/application/preferences",
                json={"last_active_discussion_id": "../unsafe"},
            ).status_code
            == 422
        )
        for invalid_value in (False, "false", 0):
            assert (
                client.put(
                    "/api/application/preferences",
                    json={"notification_permission_auto_attempted": invalid_value},
                ).status_code
                == 422
            )
        for invalid_value in ("false", 0):
            assert (
                client.put(
                    "/api/application/preferences",
                    json={"notifications_enabled": invalid_value},
                ).status_code
                == 422
            )
            assert (
                client.put(
                    "/api/application/preferences",
                    json={"prevent_sleep_while_generating": invalid_value},
                ).status_code
                == 422
            )


def test_application_appearance_modes_persist_and_reject_invalid_values(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AQA_USER_DATA_DIR", str(tmp_path / "user-data"))

    for appearance in ("dark", "light", "system"):
        with TestClient(create_app()) as client:
            response = client.put("/api/application/preferences", json={"appearance": appearance})
            assert response.status_code == 200
            assert response.json()["appearance"] == appearance
            for invalid in ("auto", "Dark", "", 1, True, [], {}):
                assert (
                    client.put(
                        "/api/application/preferences", json={"appearance": invalid}
                    ).status_code
                    == 422
                )
            unchanged = client.put("/api/application/preferences", json={})
            assert unchanged.json()["appearance"] == appearance
        with TestClient(create_app()) as restarted_client:
            restored = restarted_client.get("/api/application/preferences")
            assert restored.json()["appearance"] == appearance
