"""Focused contracts for persisted host configuration."""

from __future__ import annotations

import json

import pytest

from src.config.settings import (
    LOCAL_AI_HOST_KIND,
    LOCAL_AI_HOST_LABEL,
    Settings,
    SettingsFileError,
    _is_managed_local_ai_url,
    normalize_known_llm_hosts,
)
from src.service.host_catalog import serialize_host_entry


def test_default_settings_contain_one_managed_local_ai_host() -> None:
    settings = Settings(_env_file=None)

    assert list(settings.known_llm_hosts) == [LOCAL_AI_HOST_LABEL]
    assert settings.appearance == "system"
    assert settings.notifications_enabled is True
    assert settings.notification_permission_auto_attempted is False
    assert settings.prevent_sleep_while_generating is True
    host = settings.known_llm_hosts[LOCAL_AI_HOST_LABEL]
    assert host["kind"] == LOCAL_AI_HOST_KIND
    assert "is_favorite" not in host


def test_managed_local_ai_is_presented_as_integrated_ai() -> None:
    settings = Settings(_env_file=None)

    host = serialize_host_entry(LOCAL_AI_HOST_LABEL, settings.known_llm_hosts[LOCAL_AI_HOST_LABEL])

    assert host["configuration_id"] == LOCAL_AI_HOST_LABEL
    assert host["label"] == "Integrierte KI"
    assert host["kind"] == LOCAL_AI_HOST_KIND


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://127.0.0.1:43123/"])
def test_managed_local_ai_accepts_app_owned_loopback_ports(url: str) -> None:
    assert _is_managed_local_ai_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:8080/v1",
        "http://user@127.0.0.1:8080",
        "http://127.0.0.1:8080?target=external",
    ],
)
def test_managed_local_ai_rejects_urls_outside_exact_loopback_boundary(url: str) -> None:
    assert _is_managed_local_ai_url(url) is False


def test_normalization_keeps_model_order_and_one_favorite() -> None:
    hosts = normalize_known_llm_hosts(
        {
            "First": {
                "url": "http://first",
                "model": "main",
                "models": ["other", "main"],
                "is_favorite": True,
            },
            "Second": {"url": "http://second", "model": "second", "is_favorite": True},
        }
    )

    assert hosts["First"]["models"] == ["main", "other"]
    assert hosts["First"]["is_favorite"] is True
    assert "is_favorite" not in hosts["Second"]


def test_normalization_strips_managed_favorite_without_displacing_external_favorite() -> None:
    hosts = normalize_known_llm_hosts(
        {
            LOCAL_AI_HOST_LABEL: {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E2B-it",
                "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
                "kind": LOCAL_AI_HOST_KIND,
                "is_favorite": True,
            },
            "External": {
                "url": "https://provider.example/v1",
                "model": "provider-model",
                "is_favorite": True,
            },
        }
    )

    assert "is_favorite" not in hosts[LOCAL_AI_HOST_LABEL]
    assert hosts["External"]["is_favorite"] is True


def test_unmanaged_reserved_placeholder_is_not_promoted() -> None:
    hosts = normalize_known_llm_hosts(
        {
            "Local (Default)": {
                "url": "http://127.0.0.1:1234",
                "api_key": "",
                "model": "openai/gpt-oss-20b",
            }
        }
    )

    assert "Local (Default)" in hosts
    assert hosts["Local (Default)"]["model"] == "openai/gpt-oss-20b"
    assert hosts[LOCAL_AI_HOST_LABEL]["kind"] == LOCAL_AI_HOST_KIND


def test_same_label_custom_host_is_never_adopted() -> None:
    hosts = normalize_known_llm_hosts(
        {
            LOCAL_AI_HOST_LABEL: {
                "url": "https://provider.example/v1",
                "api_key": "secret",
                "model": "custom",
            }
        }
    )

    assert hosts[LOCAL_AI_HOST_LABEL].get("kind") is None
    assert hosts[LOCAL_AI_HOST_LABEL]["model"] == "custom"


def test_invalid_marked_local_ai_host_is_demoted() -> None:
    hosts = normalize_known_llm_hosts(
        {
            LOCAL_AI_HOST_LABEL: {
                "url": "http://remote.example:8080",
                "api_key": "",
                "model": "gemma-4-E2B-it",
                "models": ["gemma-4-E2B-it", "gemma-4-E4B-it"],
                "kind": LOCAL_AI_HOST_KIND,
            }
        }
    )

    assert hosts[LOCAL_AI_HOST_LABEL].get("kind") is None


def test_load_reads_persisted_host_list(monkeypatch, tmp_path) -> None:
    target = tmp_path / "settings.json"
    target.write_text(
        json.dumps(
            {
                "known_llm_hosts": {
                    "Custom": {
                        "url": "https://example.test/v1",
                        "api_key": "secret",
                        "model": "model",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))

    settings = Settings.load()

    assert settings.known_llm_hosts["Custom"]["model"] == "model"
    assert settings.appearance == "system"
    assert settings.notifications_enabled is True
    assert settings.prevent_sleep_while_generating is True


def test_save_persists_hosts_and_interface_preferences(monkeypatch, tmp_path) -> None:
    target = tmp_path / "nested" / "settings.json"
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))
    settings = Settings(
        _env_file=None,
        ui_locale="de",
        ai_source="external",
        local_ai_context_tokens=40_960,
        local_ai_mtp_enabled=True,
        notifications_enabled=False,
        prevent_sleep_while_generating=False,
        last_active_discussion_id="session-123",
        known_llm_hosts={
            "Custom": {"url": "https://example.test/v1", "api_key": "", "model": "model"}
        },
    )

    settings.save_user_settings()

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "known_llm_hosts": settings.known_llm_hosts,
        "ui_locale": "de",
        "appearance": "system",
        "ai_source": "external",
        "local_ai_context_tokens": 40_960,
        "local_ai_mtp_enabled": True,
        "notifications_enabled": False,
        "notification_permission_auto_attempted": False,
        "prevent_sleep_while_generating": False,
        "last_active_discussion_id": "session-123",
    }


def test_custom_model_id_survives_settings_restart_unchanged(monkeypatch, tmp_path) -> None:
    target = tmp_path / "settings.json"
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))
    custom_model = "@preset/deployment-alias"
    settings = Settings(
        _env_file=None,
        known_llm_hosts={
            "Custom": {
                "url": "https://provider.example/v1",
                "api_key": "test-key",
                "model": custom_model,
                "models": [custom_model, "catalogued-model"],
            }
        },
    )

    settings.save_user_settings()
    restored = Settings.load()

    assert restored.known_llm_hosts["Custom"]["model"] == custom_model
    assert restored.known_llm_hosts["Custom"]["models"] == [
        custom_model,
        "catalogued-model",
    ]
    assert restored.known_llm_hosts["Custom"]["api_key"] == "test-key"


def test_load_restores_valid_preferences_and_bounds_invalid_values(monkeypatch, tmp_path) -> None:
    target = tmp_path / "settings.json"
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))
    target.write_text(
        json.dumps(
            {
                "ui_locale": "de",
                "appearance": "system",
                "ai_source": "external",
                "local_ai_context_tokens": 40_960,
                "local_ai_mtp_enabled": True,
                "notifications_enabled": False,
                "notification_permission_auto_attempted": False,
                "prevent_sleep_while_generating": False,
                "last_active_discussion_id": "session-123",
            }
        ),
        encoding="utf-8",
    )

    restored = Settings.load()
    assert restored.ui_locale == "de"
    assert restored.ai_source == "external"
    assert restored.local_ai_context_tokens == 40_960
    assert restored.local_ai_mtp_enabled is True
    assert restored.notifications_enabled is False
    assert restored.notification_permission_auto_attempted is False
    assert restored.prevent_sleep_while_generating is False
    assert restored.last_active_discussion_id == "session-123"

    target.write_text(
        json.dumps(
            {
                "ui_locale": "unsupported",
                "ai_source": "unknown",
                "local_ai_context_tokens": 300_000,
                "local_ai_mtp_enabled": "yes",
                "notifications_enabled": "yes",
                "prevent_sleep_while_generating": "yes",
                "last_active_discussion_id": "../unsafe",
            }
        ),
        encoding="utf-8",
    )
    bounded = Settings.load()
    assert bounded.ui_locale == "en"
    assert bounded.ai_source == "integrated"
    assert bounded.local_ai_context_tokens == 32_768
    assert bounded.local_ai_mtp_enabled is False
    assert bounded.notifications_enabled is True
    assert bounded.prevent_sleep_while_generating is True
    assert bounded.last_active_discussion_id is None


def test_save_keeps_previous_settings_as_recovery_backup(monkeypatch, tmp_path) -> None:
    target = tmp_path / "settings.json"
    previous = {"known_llm_hosts": {"Old": {"url": "https://old.example", "model": "old"}}}
    target.write_text(json.dumps(previous), encoding="utf-8")
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))

    Settings(_env_file=None).save_user_settings()

    assert json.loads((tmp_path / "settings.json.backup").read_text(encoding="utf-8")) == previous
    assert not list(tmp_path.glob(".settings.json-*.tmp"))


def test_malformed_settings_are_preserved_and_reported(monkeypatch, tmp_path) -> None:
    target = tmp_path / "settings.json"
    target.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))

    with pytest.raises(SettingsFileError, match="original file was preserved"):
        Settings.load()

    assert target.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize("appearance", ["system", "light", "dark"])
def test_appearance_settings_persist(monkeypatch, tmp_path, appearance) -> None:
    target = tmp_path / "settings.json"
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))
    settings = Settings(appearance=appearance)
    settings.save_user_settings()
    assert json.loads(target.read_text(encoding="utf-8"))["appearance"] == appearance
    assert Settings.load().appearance == appearance


@pytest.mark.parametrize("appearance", [None, "auto", "Dark", 1, True, [], {}])
def test_invalid_stored_appearance_uses_system(monkeypatch, tmp_path, appearance) -> None:
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"appearance": appearance}), encoding="utf-8")
    monkeypatch.setenv("AQA_SETTINGS_PATH", str(target))
    assert Settings.load().appearance == "system"
