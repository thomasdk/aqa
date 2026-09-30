"""Unit tests for the non-networking live LLM test configuration helper."""

from __future__ import annotations

import pytest

from tests.live_llm_support import (
    DEFAULT_LMSTUDIO_HOST,
    LiveLLMConfigurationError,
    discover_live_llm_config,
    read_live_llm_options,
    resolve_live_model_id,
)


def test_lmstudio_defaults_keep_the_fast_smoke_budget():
    options = read_live_llm_options({})

    assert options.backend == "lmstudio"
    assert options.max_tokens == 512
    assert options.candidate_hosts == (DEFAULT_LMSTUDIO_HOST,)


def test_llamacpp_defaults_match_the_product_token_budget():
    options = read_live_llm_options({"AQA_LIVE_LLM_BACKEND": "llamacpp"})

    assert options.max_tokens == 4096


@pytest.mark.parametrize(
    "env",
    [
        {"AQA_LIVE_LLM_BACKEND": "ollama"},
        {"AQA_LIVE_LLM_MAX_TOKENS": "0"},
        {"AQA_LIVE_LLM_MAX_TOKENS": "not-a-number"},
    ],
)
def test_invalid_environment_is_rejected_without_network_access(env):
    with pytest.raises(LiveLLMConfigurationError):
        read_live_llm_options(env)


def test_explicit_model_must_be_advertised():
    assert resolve_live_model_id(["gemma-4-e2b"], "gemma-4-e2b") == "gemma-4-e2b"

    with pytest.raises(LiveLLMConfigurationError, match="nicht geladen"):
        resolve_live_model_id(["gemma-4-e2b"], "other-model")


def test_single_advertised_model_is_selected_automatically():
    assert resolve_live_model_id(["gemma-4-e2b"], None) == "gemma-4-e2b"


@pytest.mark.parametrize("model_ids", [[], ["gemma-4-e2b", "gemma-4-e4b"]])
def test_missing_or_ambiguous_automatic_model_selection_fails(model_ids):
    with pytest.raises(LiveLLMConfigurationError):
        resolve_live_model_id(model_ids, None)


def test_discovery_uses_the_configured_reachable_host_once_and_resolves_model():
    calls: list[str] = []

    def fetch_model_ids(host: str) -> list[str] | None:
        calls.append(host)
        return ["gemma-4-e2b"] if host == "http://127.0.0.1:8080" else None

    config = discover_live_llm_config(
        fetch_model_ids,
        {
            "LMSTUDIO_TEST_HOST": "http://127.0.0.1:8080/",
            "AQA_LIVE_LLM_BACKEND": "llamacpp",
        },
    )

    assert config.host == "http://127.0.0.1:8080"
    assert config.model == "gemma-4-e2b"
    assert config.backend == "llamacpp"
    assert config.max_tokens == 4096
    assert calls == ["http://127.0.0.1:8080"]
