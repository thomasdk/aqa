"""Contracts for explicit-host OpenAI-compatible adapter selection."""

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import LOCAL_AI_HOST_KIND, LOCAL_AI_HOST_LABEL, Settings
from src.llm.llm_manager import LLMManager


def _manager(settings: Settings) -> LLMManager:
    return LLMManager(settings)


def test_manager_does_not_open_a_default_connection() -> None:
    manager = _manager(Settings(_env_file=None))

    assert manager._llm_instances == {}


@patch("src.llm.llm_manager.OpenAICompatibleLLM")
def test_managed_local_ai_enables_thinking(adapter: MagicMock) -> None:
    settings = Settings(
        _env_file=None,
        known_llm_hosts={
            "Lokale KI": {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E2B-it",
                "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
                "kind": LOCAL_AI_HOST_KIND,
            }
        },
    )
    manager = _manager(settings)

    manager._create_llm_instance(
        host="http://127.0.0.1:8080",
        model_name="gemma-4-E2B-it",
        api_key=None,
        host_configuration_id=LOCAL_AI_HOST_LABEL,
    )

    assert adapter.call_args.kwargs["enable_thinking"] is True
    assert adapter.call_args.kwargs["stream_timeout"] == 600
    assert "temperature" not in adapter.call_args.kwargs
    assert "max_tokens" not in adapter.call_args.kwargs


@patch("src.llm.llm_manager.OpenAICompatibleLLM")
def test_custom_host_uses_same_adapter_without_thinking(adapter: MagicMock) -> None:
    manager = _manager(Settings(_env_file=None))

    manager._create_llm_instance(
        host="https://provider.example/v1", model_name="provider-model", api_key="key"
    )

    assert adapter.call_args.kwargs["enable_thinking"] is False
    assert adapter.call_args.kwargs["stream_timeout"] is None


def test_get_llm_requires_explicit_host_and_model() -> None:
    manager = _manager(Settings(_env_file=None))

    with pytest.raises(ValueError, match="Agentenhost"):
        manager.get_llm(model_name="model")
    with pytest.raises(ValueError, match="Agentenmodell"):
        manager.get_llm(host="http://host")


def test_resolve_request_uses_key_from_matching_host() -> None:
    settings = Settings(
        _env_file=None,
        known_llm_hosts={
            "Provider": {
                "url": "https://provider.example/v1",
                "api_key": "host-key",
                "model": "provider-model",
            }
        },
    )
    manager = _manager(settings)

    with patch.object(manager, "_available_model_ids", return_value=None):
        host, model, key = manager._resolve_request_config(
            host="https://provider.example/v1", model_name="provider-model"
        )

    assert (host, model, key) == ("https://provider.example/v1", "provider-model", "host-key")


def test_resolve_request_uses_exact_label_credential_for_duplicate_url() -> None:
    shared = "https://provider.example/v1"
    settings = Settings(
        _env_file=None,
        known_llm_hosts={
            "A": {"url": shared, "api_key": "key-a", "model": "shared"},
            "B": {"url": shared, "api_key": "key-b", "model": "shared"},
        },
    )
    manager = _manager(settings)

    with patch.object(manager, "_available_model_ids", return_value=None):
        host, model, key = manager._resolve_request_config(
            host=shared,
            host_configuration_id="B",
            model_name="shared",
        )

    assert (host, model, key) == (shared, "shared", "key-b")


def test_managed_configuration_id_resolves_raw_key_not_display_label() -> None:
    shared = "https://provider.example/v1"
    settings = Settings(_env_file=None)
    settings.known_llm_hosts = {
        LOCAL_AI_HOST_LABEL: {
            "url": shared,
            "api_key": "managed-key",
            "model": "gemma",
            "models": ["gemma"],
            "kind": LOCAL_AI_HOST_KIND,
        },
        "Integrierte KI": {
            "url": shared,
            "api_key": "external-key",
            "model": "gemma",
            "models": ["gemma"],
        },
    }
    manager = _manager(settings)

    with patch.object(manager, "_available_model_ids", return_value=None):
        _, _, key = manager._resolve_request_config(
            host=shared,
            host_configuration_id=LOCAL_AI_HOST_LABEL,
            model_name="gemma",
        )

    assert key == "managed-key"


@patch("src.llm.llm_manager.OpenAICompatibleLLM")
def test_duplicate_url_configuration_identity_controls_adapter_and_cache(
    adapter: MagicMock,
) -> None:
    shared = "http://127.0.0.1:8080"
    settings = Settings(_env_file=None)
    settings.known_llm_hosts = {
        LOCAL_AI_HOST_LABEL: {
            "url": shared,
            "api_key": "",
            "model": "gemma",
            "models": ["gemma"],
            "kind": LOCAL_AI_HOST_KIND,
        },
        "Integrierte KI": {
            "url": shared,
            "api_key": "",
            "model": "gemma",
            "models": ["gemma"],
        },
    }
    managed, external = MagicMock(), MagicMock()
    adapter.side_effect = [managed, external]
    manager = _manager(settings)

    with patch.object(manager, "_available_model_ids", return_value=None):
        assert (
            manager.get_llm(
                host=shared,
                model_name="gemma",
                host_configuration_id=LOCAL_AI_HOST_LABEL,
            )
            is managed
        )
        assert (
            manager.get_llm(
                host=shared,
                model_name="gemma",
                host_configuration_id="Integrierte KI",
            )
            is external
        )

    assert adapter.call_args_list[0].kwargs["enable_thinking"] is True
    assert adapter.call_args_list[1].kwargs["enable_thinking"] is False


@patch("src.llm.llm_manager.OpenAICompatibleLLM")
def test_request_activity_callbacks_are_limited_to_managed_local_ai(
    adapter: MagicMock,
) -> None:
    shared = "http://127.0.0.1:8080"
    settings = Settings(_env_file=None)
    settings.known_llm_hosts = {
        LOCAL_AI_HOST_LABEL: {
            "url": shared,
            "api_key": "",
            "model": "gemma",
            "models": ["gemma"],
            "kind": LOCAL_AI_HOST_KIND,
        },
        "External": {
            "url": shared,
            "api_key": "",
            "model": "gemma",
            "models": ["gemma"],
        },
    }
    manager = _manager(settings)
    active, idle = MagicMock(), MagicMock()
    manager.set_managed_local_ai_request_callbacks(active, idle)

    with patch.object(manager, "_available_model_ids", return_value=None):
        manager.get_llm(
            host=shared,
            model_name="gemma",
            host_configuration_id=LOCAL_AI_HOST_LABEL,
        )
        manager.get_llm(
            host=shared,
            model_name="gemma",
            host_configuration_id="External",
        )

    assert adapter.call_args_list[0].kwargs["request_started"] is active
    assert adapter.call_args_list[0].kwargs["request_finished"] is idle
    assert adapter.call_args_list[1].kwargs["request_started"] is None
    assert adapter.call_args_list[1].kwargs["request_finished"] is None


@patch("src.llm.llm_manager.OpenAICompatibleLLM")
def test_callbacks_attach_to_an_existing_managed_adapter_only(adapter: MagicMock) -> None:
    shared = "http://127.0.0.1:8080"
    settings = Settings(_env_file=None)
    settings.known_llm_hosts = {
        LOCAL_AI_HOST_LABEL: {
            "url": shared,
            "api_key": "",
            "model": "gemma",
            "models": ["gemma"],
            "kind": LOCAL_AI_HOST_KIND,
        }
    }
    instance = MagicMock()
    adapter.return_value = instance
    manager = _manager(settings)
    with patch.object(manager, "_available_model_ids", return_value=None):
        manager.get_llm(
            host=shared,
            model_name="gemma",
            host_configuration_id=LOCAL_AI_HOST_LABEL,
        )
    active, idle = MagicMock(), MagicMock()

    manager.set_managed_local_ai_request_callbacks(active, idle)

    instance.set_request_activity_callbacks.assert_called_once_with(active, idle)


def test_external_custom_model_is_not_rejected_by_advertised_catalogue() -> None:
    settings = Settings(
        _env_file=None,
        known_llm_hosts={
            "External": {
                "url": "https://provider.example/v1",
                "api_key": "key",
                "model": "deployment-alias",
                "models": ["deployment-alias"],
            }
        },
    )
    manager = _manager(settings)

    with patch.object(manager, "_available_model_ids", return_value=["advertised-model"]) as listed:
        resolved = manager._resolve_request_config(
            host="https://provider.example/v1",
            model_name="deployment-alias",
            host_configuration_id="External",
        )

    assert resolved == ("https://provider.example/v1", "deployment-alias", "key")
    listed.assert_not_called()


def test_managed_local_ai_still_requires_advertised_model() -> None:
    settings = Settings(
        _env_file=None,
        known_llm_hosts={
            LOCAL_AI_HOST_LABEL: {
                "url": "http://127.0.0.1:8080",
                "api_key": "",
                "model": "gemma-4-E2B-it",
                "models": ["gemma-4-E2B-it", "gemma-4-E4B-it", "gemma-4-12B-it"],
                "kind": LOCAL_AI_HOST_KIND,
            }
        },
    )
    manager = _manager(settings)

    with patch.object(manager, "_available_model_ids", return_value=["different-model"]):
        with pytest.raises(ValueError, match="nicht verfügbar"):
            manager._resolve_request_config(
                host="http://127.0.0.1:8080",
                model_name="gemma-4-E2B-it",
                host_configuration_id=LOCAL_AI_HOST_LABEL,
            )


@patch("src.llm.llm_manager.OpenAICompatibleLLM")
def test_get_llm_caches_by_explicit_host_and_model(adapter: MagicMock) -> None:
    first, second = MagicMock(), MagicMock()
    adapter.side_effect = [first, second]
    manager = _manager(Settings(_env_file=None))

    with patch.object(manager, "_available_model_ids", return_value=["one", "two"]):
        assert manager.get_llm(host="http://host", model_name="one") is first
        assert manager.get_llm(host="http://host", model_name="one") is first
        assert manager.get_llm(host="http://host", model_name="two") is second

    assert adapter.call_count == 2


@patch("src.llm.llm_manager.requests.get")
def test_check_connection_uses_openai_model_endpoint(mock_get: MagicMock) -> None:
    response = MagicMock()
    mock_get.return_value = response

    LLMManager.check_connection("http://host", api_key="key")

    mock_get.assert_called_once_with(
        "http://host/v1/models",
        headers={"Content-Type": "application/json", "Authorization": "Bearer key"},
        timeout=5,
        stream=True,
        allow_redirects=False,
    )
    response.close.assert_called_once_with()
