"""HTTP routes for the configured LLM-host catalogue."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from copy import deepcopy
from functools import wraps
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config.settings import (
    LOCAL_AI_HOST_KIND,
    LOCAL_AI_HOST_LABEL,
    _clean_model_name,
    _is_valid_managed_local_ai_entry,
    _local_ai_host,
    _normalize_host_entry,
)
from src.config.user_data import mutable_data_lock
from src.service.api_errors import api_error
from src.service.api_schemas import (
    HostDeletePreviewRequest,
    HostDeletePreviewResponse,
    HostDeleteRequest,
    HostDeleteResponse,
    HostInfoResponse,
    HostModelsResponse,
)
from src.service.host_catalog import (
    clear_favorite_from_all_hosts,
    get_host_by_index,
    merge_model_list,
    normalize_model_context_tokens,
    serialize_host_entry,
    validate_url,
)
from src.service.routers.dependencies import ContextDependency

router = APIRouter(tags=["hosts"])
_HOST_REVISION_KEY = secrets.token_bytes(32)


def _serializes_mutable_data(function):
    """Keep a host read-modify-write operation atomic against imports."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutable_data_lock:
            return function(*args, **kwargs)

    return wrapped


class HostCreateRequest(BaseModel):
    """Body for POST /api/hosts."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, description="Human-readable label")
    url: str = Field(..., min_length=1, description="Host URL (http:// or https://)")
    model: str = Field(..., min_length=1, description="Default model name")
    models: list[str] | None = Field(default=None, description="Selectable model names")
    model_context_tokens: dict[str, int] = Field(
        default_factory=dict,
        description="Optional context-window limit by selected model ID",
    )
    kind: str | None = Field(default=None, description="Optional host kind marker")
    api_key: str | None = Field(default=None, description="Optional API key")
    is_favorite: bool = Field(
        default=False, description="Whether this is the preferred external host"
    )

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        label = value.strip()
        if not label:
            raise ValueError("Host label must contain non-whitespace text")
        return label

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("Model name must contain non-whitespace text")
        return model


class HostUpdateRequest(BaseModel):
    """Body for PUT /api/hosts/{index}; omitted fields are preserved."""

    model_config = ConfigDict(extra="forbid")

    configuration_id: str = Field(..., min_length=1, description="Expected saved host identity")
    label: str | None = Field(default=None, min_length=1, description="New label")
    url: str | None = Field(default=None, min_length=1, description="New URL")
    model: str | None = Field(default=None, min_length=1, description="New model name")
    models: list[str] | None = Field(default=None, description="Selectable model names")
    model_context_tokens: dict[str, int] | None = Field(
        default=None,
        description="Replace optional context-window limits by selected model ID",
    )
    kind: str | None = Field(default=None, description="Optional host kind marker")
    api_key: str | None = Field(
        default=None, description="New API key — omit to keep, null/empty to clear"
    )
    is_favorite: bool | None = Field(default=None, description="Set preferred external host")

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        label = value.strip()
        if not label:
            raise ValueError("Host label must contain non-whitespace text")
        return label

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        model = value.strip()
        if not model:
            raise ValueError("Model name must contain non-whitespace text")
        return model


class TestHostResponse(BaseModel):
    ok: bool
    code: str
    message: str
    models: list[str]


class DraftHostTestRequest(BaseModel):
    """Connection details used only for testing an unsaved external host."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=1, description="Host URL (http:// or https://)")
    api_key: str | None = Field(default=None, description="Optional API key")


class SavedHostTestRequest(DraftHostTestRequest):
    """Edit-test details tied to the saved host expected at the route index."""

    configuration_id: str = Field(..., min_length=1, description="Expected saved host identity")


@router.get("/api/hosts", response_model=list[HostInfoResponse])
def list_hosts(context: ContextDependency) -> list[dict[str, Any]]:
    return [
        serialize_host_entry(label, info)
        for label, info in context.settings.known_llm_hosts.items()
    ]


def _test_connection(context: Any, host: str, api_key: str | None) -> TestHostResponse:
    """Test an OpenAI-compatible host without mutating the host catalogue."""
    try:
        context.llm_manager.check_connection(
            host=host,
            api_key=api_key or None,
            timeout=5,
        )
        models = context.llm_manager._list_available_model_ids(
            host=host,
            api_key=api_key or None,
            timeout=5,
        )
        return TestHostResponse(
            ok=True,
            code="connection_established",
            message="Connection established",
            models=models or [],
        )
    except Exception:
        return TestHostResponse(
            ok=False,
            code="connection_failed",
            message="Connection failed",
            models=[],
        )


def _host_by_label(context: Any, label: str) -> dict[str, Any]:
    info = context.settings.known_llm_hosts.get(label)
    if not isinstance(info, dict):
        raise api_error(404, "host_not_found", "Host not found.")
    if _is_valid_managed_local_ai_entry(info):
        raise api_error(
            409,
            "managed_host_delete_forbidden",
            "Manage Integrated AI through the Integrated AI page.",
        )
    return info


def _host_revision(label: str, info: dict[str, Any]) -> str:
    """Return an opaque composite precondition without exposing its credential digest."""
    revision_input = {
        "host": serialize_host_entry(label, info),
        "credential": str(info.get("api_key", "")),
    }
    payload = json.dumps(revision_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(_HOST_REVISION_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _require_host_identity(actual_label: str, expected_label: str) -> None:
    """Reject stale index operations before using or changing the resolved host."""
    if actual_label != expected_label:
        raise api_error(
            409,
            "host_catalog_changed",
            "The host catalogue changed. Refresh the host list and try again.",
        )


@router.post("/api/hosts/test-connection", response_model=TestHostResponse)
def test_draft_host(payload: DraftHostTestRequest, context: ContextDependency) -> TestHostResponse:
    """Test an unsaved host using only the details supplied by the dialog."""
    url = validate_url(payload.url)
    return _test_connection(context, url, payload.api_key)


@router.get("/api/hosts/{index}/models", response_model=HostModelsResponse)
def get_host_models(index: int, context: ContextDependency) -> dict[str, list[str]]:
    """Load currently advertised model IDs from a configured host."""
    _, host_info = get_host_by_index(context, index)
    host = validate_url(host_info.get("url", ""))
    try:
        models = context.llm_manager._list_available_model_ids(
            host=host,
            api_key=host_info.get("api_key") or None,
            timeout=5,
        )
    except Exception as error:
        raise api_error(
            502,
            "host_models_unavailable",
            "Models could not be loaded from the host.",
        ) from error
    return {"models": models or []}


@router.post("/api/hosts", status_code=201, response_model=HostInfoResponse)
@_serializes_mutable_data
def create_host(payload: HostCreateRequest, context: ContextDependency) -> dict[str, Any]:
    """Add a new LLM host to the known-host catalogue."""
    url = validate_url(payload.url)
    if payload.kind == LOCAL_AI_HOST_KIND:
        raise HTTPException(
            status_code=422,
            detail="Der Typ local_ai ist für die verwaltete integrierte KI reserviert.",
        )
    if payload.label in context.settings.known_llm_hosts:
        raise HTTPException(
            status_code=409, detail=f"Host with label '{payload.label}' already exists"
        )

    models = merge_model_list(
        payload.model, payload.models if payload.models is not None else [payload.model]
    )
    context_limits = normalize_model_context_tokens(payload.model_context_tokens, models)
    if set(payload.model_context_tokens) - set(models) or any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in payload.model_context_tokens.values()
    ):
        raise HTTPException(
            status_code=422, detail="Context limits must be positive values for selected models"
        )
    entry = _normalize_host_entry(
        {
            "url": url,
            "model": payload.model,
            "models": models,
            "model_context_tokens": context_limits,
            "api_key": payload.api_key or "",
            "kind": payload.kind,
            "is_favorite": payload.is_favorite,
        }
    )
    if entry.get("kind") is None:
        entry.pop("kind", None)
    original_hosts = deepcopy(context.settings.known_llm_hosts)
    if entry.get("is_favorite"):
        clear_favorite_from_all_hosts(context)
    context.settings.known_llm_hosts[payload.label] = entry
    try:
        context.settings.save_user_settings()
    except Exception as error:
        context.settings.known_llm_hosts = original_hosts
        raise api_error(
            500,
            "host_create_persistence_failed",
            "The host was not added because settings could not be saved.",
        ) from error
    return serialize_host_entry(payload.label, entry)


def _validate_host_update(info: dict[str, Any], update_data: dict[str, Any]) -> None:
    """Reject attempts to mutate the application-managed Local AI host."""

    if update_data.get("kind") == LOCAL_AI_HOST_KIND:
        raise HTTPException(status_code=422, detail="Managed Local AI reserves the local_ai type.")
    if not _is_valid_managed_local_ai_entry(info):
        return
    protected = {"label", "url", "model", "models", "api_key", "kind"}
    if protected.intersection(update_data):
        raise HTTPException(status_code=422, detail="Manage Local AI technical fields in Local AI.")
    if update_data.get("is_favorite") is True:
        raise HTTPException(status_code=422, detail="Only external hosts can be preferred.")


def _updated_models(info: dict[str, Any], update_data: dict[str, Any]) -> tuple[str, list[str]]:
    """Return the retained preferred model and the current model list."""

    current_preferred = _clean_model_name(info.get("model")) or ""
    current_models = info.get("models") if isinstance(info.get("models"), (list, tuple)) else []
    normalized_current = merge_model_list(current_preferred, current_models)
    new_model = update_data.get("model")
    submitted_models = update_data.get("models")
    if new_model is None and submitted_models is None:
        return current_preferred, normalized_current
    preferred = _clean_model_name(new_model) if new_model is not None else current_preferred
    return current_preferred, merge_model_list(
        preferred, [*normalized_current, *(submitted_models or [])]
    )


def _updated_context_limits(
    info: dict[str, Any], update_data: dict[str, Any], models: list[str]
) -> dict[str, int]:
    """Validate and normalize model context limits for the final model list."""

    raw_limits = update_data.get("model_context_tokens", info.get("model_context_tokens", {}))
    invalid = (
        not isinstance(raw_limits, dict)
        or set(raw_limits) - set(models)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in raw_limits.values()
        )
    )
    if invalid:
        raise HTTPException(
            status_code=422, detail="Context limits must be positive values for selected models"
        )
    return normalize_model_context_tokens(raw_limits, models)


@router.put("/api/hosts/{index}", response_model=HostInfoResponse)
@_serializes_mutable_data
def update_host(
    index: int, payload: HostUpdateRequest, context: ContextDependency
) -> dict[str, Any]:
    """Update one host while preserving omitted and unrecognized fields."""
    label, info = get_host_by_index(context, index)
    update_data = payload.model_dump(exclude_unset=True)
    _require_host_identity(label, update_data.pop("configuration_id"))
    _validate_host_update(info, update_data)

    new_label = update_data.get("label", label)
    new_url = update_data.get("url", info.get("url", ""))
    new_api_key = info.get("api_key", "")
    if "api_key" in update_data:
        new_api_key = update_data["api_key"] or ""
    if "url" in update_data:
        new_url = validate_url(new_url)

    current_preferred, final_models = _updated_models(info, update_data)

    new_kind = update_data.get("kind", info.get("kind"))
    final_context_limits = _updated_context_limits(info, update_data, final_models)
    new_is_favorite = update_data.get("is_favorite")
    if new_label != label and new_label in context.settings.known_llm_hosts:
        raise HTTPException(status_code=409, detail=f"Host with label '{new_label}' already exists")
    original_hosts = deepcopy(context.settings.known_llm_hosts)
    if new_is_favorite is True:
        clear_favorite_from_all_hosts(context)

    updated_info: dict[str, Any] = {
        "url": new_url,
        "model": final_models[0] if final_models else current_preferred,
        "api_key": new_api_key,
        "models": final_models,
        "model_context_tokens": final_context_limits,
    }
    if new_kind is not None:
        updated_info["kind"] = new_kind
    if new_is_favorite is not None:
        updated_info["is_favorite"] = new_is_favorite
    for key, value in info.items():
        if key not in updated_info:
            updated_info[key] = value
    if new_label != label:
        del context.settings.known_llm_hosts[label]
    context.settings.known_llm_hosts[new_label] = updated_info
    try:
        context.settings.save_user_settings()
    except Exception as error:
        context.settings.known_llm_hosts = original_hosts
        raise api_error(
            500,
            "host_update_persistence_failed",
            "Host changes could not be saved.",
        ) from error
    return serialize_host_entry(new_label, updated_info)


@router.post("/api/hosts/{index}/reset-managed-local-ai")
@_serializes_mutable_data
def reset_managed_local_ai_host(index: int, context: ContextDependency) -> dict[str, Any]:
    """Restore the factory configuration of the verified managed host."""
    label, info = get_host_by_index(context, index)
    if label != LOCAL_AI_HOST_LABEL or not _is_valid_managed_local_ai_entry(info):
        raise HTTPException(status_code=409, detail="Host is not a managed Integrated AI entry")
    restored = _local_ai_host()
    previous_hosts = deepcopy(context.settings.known_llm_hosts)
    context.settings.known_llm_hosts[label] = restored
    try:
        context.settings.save_user_settings()
    except Exception as error:
        context.settings.known_llm_hosts = previous_hosts
        raise api_error(
            500,
            "host_reset_persistence_failed",
            "Integrated AI settings could not be restored.",
        ) from error
    return serialize_host_entry(label, restored)


@router.post(
    "/api/hosts/delete-preview",
    response_model=HostDeletePreviewResponse,
)
@_serializes_mutable_data
def preview_host_deletion(
    payload: HostDeletePreviewRequest, context: ContextDependency
) -> dict[str, Any]:
    """Freeze the secret-free consequences shown before destructive confirmation."""
    info = _host_by_label(context, payload.label)
    if len(context.settings.known_llm_hosts) <= 1:
        raise api_error(
            422,
            "host_delete_last_configuration",
            "The final host configuration cannot be deleted.",
        )
    return {
        "label": payload.label,
        "revision": _host_revision(payload.label, info),
        "is_preferred": bool(info.get("is_favorite")),
        "credential_will_be_removed": bool(info.get("api_key")),
        "saved_sessions": context.discussion.sessions_referencing_host(
            payload.label, info.get("url", "")
        ),
    }


@router.post("/api/hosts/delete", response_model=HostDeleteResponse)
@_serializes_mutable_data
def delete_host(payload: HostDeleteRequest, context: ContextDependency) -> dict[str, Any]:
    """Delete one preflighted host and restore memory if durable persistence fails."""
    info = _host_by_label(context, payload.label)
    if len(context.settings.known_llm_hosts) <= 1:
        raise api_error(
            422,
            "host_delete_last_configuration",
            "The final host configuration cannot be deleted.",
        )
    if _host_revision(payload.label, info) != payload.revision:
        raise api_error(
            409,
            "host_catalog_changed",
            "The host configuration changed. Review its current impact before deleting it.",
        )

    previous_hosts = deepcopy(context.settings.known_llm_hosts)
    credential_removed = bool(info.get("api_key"))
    del context.settings.known_llm_hosts[payload.label]
    try:
        context.settings.save_user_settings()
    except Exception as exc:
        context.settings.known_llm_hosts = previous_hosts
        raise api_error(
            500,
            "host_delete_persistence_failed",
            "The host was not deleted because settings could not be saved.",
        ) from exc
    return {
        "deleted": True,
        "label": payload.label,
        "credential_removed": credential_removed,
    }


@router.post("/api/hosts/{index}/test")
def test_host(
    index: int,
    context: ContextDependency,
    payload: SavedHostTestRequest,
) -> TestHostResponse:
    """Test a saved host or an edit draft without mutating the catalogue.

    An edit dialog never receives the stored key. An omitted or blank draft key
    therefore reuses the saved key only while testing the unchanged saved URL;
    a non-blank draft key is used only for the test and is never persisted.
    """
    label, info = get_host_by_index(context, index)
    _require_host_identity(label, payload.configuration_id)
    url = validate_url(payload.url)
    replacement_key = (payload.api_key or "").strip()
    saved_url = validate_url(info.get("url", ""))
    # A stored credential is scoped to the saved endpoint. Never forward it to
    # an edited URL unless the user supplied a replacement credential.
    api_key = replacement_key or (info.get("api_key") if url == saved_url else None)
    return _test_connection(context, url, api_key)
