"""Pure configuration helpers for opt-in live LLM integration tests."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

SUPPORTED_LIVE_LLM_BACKENDS = frozenset({"llamacpp", "lmstudio"})
DEFAULT_LMSTUDIO_HOST = "http://127.0.0.1:1234"


class LiveLLMConfigurationError(ValueError):
    """Raised when an opted-in live LLM test cannot select one model."""


@dataclass(frozen=True)
class LiveLLMOptions:
    backend: str
    model: str | None
    max_tokens: int
    candidate_hosts: tuple[str, ...]


@dataclass(frozen=True)
class LiveLLMConfig:
    backend: str
    host: str
    model: str
    max_tokens: int


def _default_max_tokens(backend: str) -> int:
    return 4096 if backend == "llamacpp" else 512


def read_live_llm_options(env: Mapping[str, str] | None = None) -> LiveLLMOptions:
    """Read and validate live-test options without making network calls."""
    source = os.environ if env is None else env
    backend = source.get("AQA_LIVE_LLM_BACKEND", "lmstudio").strip().lower()
    if backend not in SUPPORTED_LIVE_LLM_BACKENDS:
        choices = ", ".join(sorted(SUPPORTED_LIVE_LLM_BACKENDS))
        raise LiveLLMConfigurationError(
            f"AQA_LIVE_LLM_BACKEND must be one of {choices}; received {backend or '<empty>'}."
        )

    raw_budget = source.get("AQA_LIVE_LLM_MAX_TOKENS", "").strip()
    if raw_budget:
        try:
            max_tokens = int(raw_budget)
        except ValueError as exc:
            raise LiveLLMConfigurationError(
                "AQA_LIVE_LLM_MAX_TOKENS must be a positive integer."
            ) from exc
        if max_tokens <= 0:
            raise LiveLLMConfigurationError("AQA_LIVE_LLM_MAX_TOKENS must be a positive integer.")
    else:
        max_tokens = _default_max_tokens(backend)

    configured_host = source.get("LMSTUDIO_TEST_HOST", "").strip().rstrip("/")
    candidates = [configured_host] if configured_host else []
    if DEFAULT_LMSTUDIO_HOST not in candidates:
        candidates.append(DEFAULT_LMSTUDIO_HOST)

    model = source.get("AQA_LIVE_LLM_MODEL", "").strip() or None
    return LiveLLMOptions(
        backend=backend,
        model=model,
        max_tokens=max_tokens,
        candidate_hosts=tuple(candidates),
    )


def resolve_live_model_id(advertised_ids: list[str], requested_model: str | None) -> str:
    """Select the requested model or the only model advertised by a host."""
    if requested_model:
        if requested_model in advertised_ids:
            return requested_model
        available = ", ".join(advertised_ids) or "keine"
        raise LiveLLMConfigurationError(
            f"AQA_LIVE_LLM_MODEL '{requested_model}' ist nicht geladen. Verfügbar: {available}."
        )
    if len(advertised_ids) == 1:
        return advertised_ids[0]
    if not advertised_ids:
        raise LiveLLMConfigurationError("Der Host meldet keine geladenen Modelle unter /v1/models.")
    raise LiveLLMConfigurationError(
        "Der Host meldet mehrere Modelle. AQA_LIVE_LLM_MODEL muss eines davon auswählen: "
        + ", ".join(advertised_ids)
    )


def discover_live_llm_config(
    fetch_model_ids: Callable[[str], list[str] | None],
    env: Mapping[str, str] | None = None,
) -> LiveLLMConfig:
    """Resolve one reachable host and one model using an injected fetcher."""
    options = read_live_llm_options(env)
    for host in options.candidate_hosts:
        model_ids = fetch_model_ids(host)
        if model_ids is None:
            continue
        return LiveLLMConfig(
            backend=options.backend,
            host=host,
            model=resolve_live_model_id(model_ids, options.model),
            max_tokens=options.max_tokens,
        )
    tried = ", ".join(options.candidate_hosts)
    raise LiveLLMConfigurationError(
        f"Kein Live-LLM-Host war unter /v1/models erreichbar. Geprüft: {tried}."
    )
