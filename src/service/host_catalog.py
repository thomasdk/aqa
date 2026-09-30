"""Host-catalog helpers shared by the HTTP transport layer.

The helpers intentionally return redacted host records: API keys remain in
``Settings`` and never cross the API boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException

from src.config.settings import (
    LOCAL_AI_HOST_KIND,
    LOCAL_AI_HOST_LABEL,
    _clean_model_name,
    _is_valid_managed_local_ai_entry,
)
from src.service.api_errors import api_error

INTEGRATED_AI_DISPLAY_LABEL = "Integrierte KI"


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def validate_url(url: str) -> str:
    """Return a normalized absolute HTTP(S) provider URL or raise a stable error."""

    normalized = url.strip() if isinstance(url, str) else ""
    parsed = None
    hostname = None
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        # Accessing ``port`` makes urllib reject malformed numeric port values.
        _ = parsed.port
    except ValueError:
        hostname = None

    if (
        not normalized
        or any(character.isspace() for character in normalized)
        or parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise api_error(
            422,
            "host_url_invalid",
            "Enter a valid URL beginning with http:// or https://.",
        )
    return normalized


def clear_favorite_from_all_hosts(context: Any) -> None:
    """Clear the external-host preference marker from every configured host."""
    for entry in context.settings.known_llm_hosts.values():
        entry.pop("is_favorite", None)


def merge_model_list(preferred: str | None, candidates: list[Any]) -> list[str]:
    """Return cleaned, unique model identifiers with the preferred one first."""
    models: list[str] = []
    if preferred:
        models.append(preferred)
    for raw in candidates:
        name = _clean_model_name(raw)
        if name and name not in models:
            models.append(name)
    return models


def normalize_model_context_tokens(raw: Any, models: list[str]) -> dict[str, int]:
    """Return the safe, selected-model subset of optional context limits."""

    if not isinstance(raw, Mapping):
        return {}
    allowed = set(models)
    normalized: dict[str, int] = {}
    for model_id, value in raw.items():
        if (
            isinstance(model_id, str)
            and model_id in allowed
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        ):
            normalized[model_id] = value
    return normalized


def serialize_host_entry(label: str, info: Mapping[str, Any]) -> dict[str, Any]:
    """Return the browser-safe representation of one configured host."""
    is_managed_local_ai = label == LOCAL_AI_HOST_LABEL and _is_valid_managed_local_ai_entry(info)
    raw_models = info.get("models")
    selectable_models = merge_model_list(
        _clean_model_name(info.get("model")),
        list(raw_models) if isinstance(raw_models, (list, tuple)) else [],
    )
    model_context_tokens = normalize_model_context_tokens(
        info.get("model_context_tokens"), selectable_models
    )
    return {
        "configuration_id": label,
        # Keep the persisted host key stable while presenting the managed
        # service with the same terminology used everywhere else in the UI.
        "label": INTEGRATED_AI_DISPLAY_LABEL if is_managed_local_ai else label,
        "url": info.get("url", ""),
        "model": selectable_models[0] if selectable_models else "",
        "models": selectable_models,
        "kind": (LOCAL_AI_HOST_KIND if is_managed_local_ai else info.get("kind") or None),
        "has_api_key": bool(info.get("api_key")),
        "is_favorite": False if is_managed_local_ai else bool(info.get("is_favorite")),
        "model_context_tokens": model_context_tokens,
        "context_tokens": (
            _positive_int(info.get("context_tokens")) if is_managed_local_ai else None
        ),
    }


def get_host_by_index(context: Any, index: int) -> tuple[str, dict[str, Any]]:
    """Return a host by its UI index or raise the public 404 response."""
    hosts = context.settings.known_llm_hosts
    labels = list(hosts.keys())
    if index < 0 or index >= len(labels):
        raise HTTPException(status_code=404, detail="Host not found")
    label = labels[index]
    return label, hosts[label]
