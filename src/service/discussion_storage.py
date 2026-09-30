"""Atomic JSON persistence for discussion snapshots."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from loguru import logger

from src.config.user_data import mutable_data_lock
from src.prompts.session_types import effective_session_input_value
from src.service.discussion_prompts import (
    RESEARCHER_NOTE_REMINDER_HEADING,
    RESEARCHER_NOTE_REMINDER_TEXT,
)

DEFAULT_AGENT_COLOR = "#333333"


class SessionDeletionRollbackError(OSError):
    """A failed deletion whose rollback could not restore the full catalogue."""

    def __init__(self, deleted_ids: list[str], retained_ids: list[str]):
        super().__init__("session deletion rollback was incomplete")
        self.deleted_ids = deleted_ids
        self.retained_ids = retained_ids
        self.was_active = False


_EXPORT_COPY = {
    "de": {
        "created": "Erstellt",
        "rounds": "Runden",
        "session_type": "Session-Typ",
        "material_type": "Material-Typ",
        "analysis_context": "Analysekontext",
        "perspectives": "Beteiligte Perspektiven",
        "temperature": "Temp:",
        "material": "Material",
        "missing_material": "Kein Material angegeben",
        "initial_instruction": "Startauftrag (erste Runde)",
        "missing_value": "Nicht angegeben",
        "discussion": "Diskussionsverlauf",
        "round": "Runde",
        "round_configuration": "Konfiguration dieser Runde",
        "perspective": "Perspektive",
        "role": "Rolle",
        "host": "Host",
        "model": "Modell",
        "status": "Status",
        "round_status": {
            "in_progress": "unterbrochen (in Bearbeitung)",
            "interrupted": "Unterbrochen",
            "failed": "Fehlgeschlagen",
        },
        "moderator": "Moderator",
        "context_status": "Kontextstatus",
        "excluded_from_context": "nicht in nachfolgende Agentenrunden eingespeist.",
        "message_note": "Notiz zur Nachricht",
        "synthesis": "Synthese",
        "footer": "Exportiert aus AQA",
    },
    "en": {
        "created": "Created",
        "rounds": "Rounds",
        "session_type": "Session type",
        "material_type": "Material type",
        "analysis_context": "Analysis context",
        "perspectives": "Participating perspectives",
        "temperature": "Temp.",
        "material": "Material",
        "missing_material": "No material provided",
        "initial_instruction": "Initial instruction (first round)",
        "missing_value": "Not provided",
        "discussion": "Discussion transcript",
        "round": "Round",
        "round_configuration": "Configuration for this round",
        "perspective": "Perspective",
        "role": "Role",
        "host": "Host",
        "model": "Model",
        "status": "Status",
        "round_status": {
            "in_progress": "interrupted (in progress)",
            "interrupted": "Interrupted",
            "failed": "Failed",
        },
        "moderator": "Moderator",
        "context_status": "Context status",
        "excluded_from_context": "not included in subsequent agent rounds.",
        "message_note": "Message note",
        "synthesis": "Synthesis",
        "footer": "Exported from AQA",
    },
}


def _serializes_mutable_data(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with mutable_data_lock:
            return function(*args, **kwargs)

    return wrapped


# Restrict file IDs before filesystem access to reject traversal and absolute paths.
_FILENAME_STEM_PATTERN = re.compile(r"^[A-Za-z0-9._\-]+$")


def _required_perspective_number(value: Any, field_name: str) -> int:
    """Validate the current persisted stable-identity contract."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} requires a positive perspective_number")
    return value


@dataclass
class StoredMessage:
    """A path- and secret-free message in a persisted discussion."""

    id: str
    role: str  # "user", "agent"
    content: str
    status: str = "completed"
    agent_name: str | None = None
    theory_label: str | None = None
    note: str = ""
    include_in_agent_context: bool = True
    include_note_in_agent_context: bool = False
    client_id: str | None = None
    color: str | None = None
    agent_index: int | None = None
    perspective_number: int | None = None
    error: str | None = None
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    usage_available: bool | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    context_usage_available: bool | None = None
    input_context_tokens: int | None = None
    context_window_tokens: int | None = None
    context_tokens_exact: bool | None = None
    omitted_round_numbers: list[int] = field(default_factory=list)


@dataclass
class StoredRound:
    """One discussion round in the persisted snapshot format."""

    round_number: int
    status: str = "completed"
    messages: list[StoredMessage] = field(default_factory=list)
    provider_provenance: list[StoredProviderProvenance] = field(default_factory=list)


@dataclass(frozen=True)
class StoredProviderProvenance:
    """Safe role and provider configuration frozen for one round participant."""

    kind: str
    client_id: str | None
    prompt_id: str
    prompt_label: str
    perspective_number: int | None
    temperature: float | None
    host_configuration_id: str | None
    host_label: str | None
    api_host: str
    model_id: str


@dataclass
class StoredAgent:
    """Non-secret agent configuration required to resume a discussion."""

    name: str
    client_id: str | None = None
    prompt_id: str | None = None
    prompt_label: str = ""
    color: str = DEFAULT_AGENT_COLOR
    temperature: float | None = None
    llm_id: str | None = None
    api_host: str | None = None
    host_configuration_id: str | None = None
    host_label: str | None = None
    max_tokens: int | None = None
    enabled: bool = True
    perspective_number: int = 0


@dataclass
class StoredSynthesisConfig:
    """Safe, persisted configuration for the round synthesis provider."""

    enabled: bool
    api_host: str | None
    llm_id: str | None
    temperature: float | None = None
    host_configuration_id: str | None = None
    host_label: str | None = None


@dataclass
class StoredPromptSnapshot:
    """Immutable prompt assets and assembly policy captured at session start."""

    layout: str = ""
    session: dict[str, str] = field(default_factory=dict)
    globals: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, str] | None = None
    target_language: str = ""
    context_policy: dict[str, Any] = field(default_factory=dict)
    used_global_ids: list[str] = field(default_factory=list)
    used_role_ids: list[str] = field(default_factory=list)
    synthesis_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": self.layout,
            "session": self.session,
            "globals": self.globals,
            "roles": self.roles,
            "synthesis": self.synthesis,
            "target_language": self.target_language,
            "context_policy": self.context_policy,
            "used_global_ids": self.used_global_ids,
            "used_role_ids": self.used_role_ids,
            "synthesis_used": self.synthesis_used,
        }

    @classmethod
    def from_dict(cls, data: Any) -> StoredPromptSnapshot:
        required = {
            "layout",
            "session",
            "globals",
            "roles",
            "synthesis",
            "target_language",
            "context_policy",
            "used_global_ids",
            "used_role_ids",
            "synthesis_used",
        }
        if not isinstance(data, dict) or required.difference(data):
            raise ValueError("prompt_snapshot is required and must be complete")
        if not isinstance(data["layout"], str) or not isinstance(data["target_language"], str):
            raise ValueError("prompt_snapshot has invalid text fields")
        if not isinstance(data["session"], dict) or not isinstance(data["globals"], list):
            raise ValueError("prompt_snapshot has invalid session or globals")
        if not isinstance(data["roles"], list) or not isinstance(data["context_policy"], dict):
            raise ValueError("prompt_snapshot has invalid roles or policy")
        if not isinstance(data["synthesis_used"], bool):
            raise ValueError("prompt_snapshot.synthesis_used must be boolean")
        if not all(
            isinstance(item, str) for item in data["used_global_ids"] + data["used_role_ids"]
        ):
            raise ValueError("prompt_snapshot usage ids must be strings")
        return cls(**{key: data[key] for key in required})

    @property
    def is_empty(self) -> bool:
        return not any((self.layout, self.session, self.globals, self.roles, self.synthesis))


_DISCUSSION_KEYS = frozenset(
    {
        "id",
        "created",
        "updated",
        "title",
        "material",
        "initial_question",
        "material_type",
        "session_type",
        "target_language",
        "prompt_snapshot",
        "input_values",
        "input_definitions",
        "include_unchanged_research_material_context_in_prompt",
        "sequential_mode",
        "is_favorite",
        "synthesis",
        "agents",
        "rounds",
    }
)
_SYNTHESIS_KEYS = frozenset(
    {"enabled", "api_host", "llm_id", "host_configuration_id", "host_label", "temperature"}
)
_AGENT_KEYS = frozenset(
    {
        "name",
        "client_id",
        "prompt_id",
        "prompt_label",
        "color",
        "temperature",
        "llm_id",
        "api_host",
        "host_configuration_id",
        "host_label",
        "max_tokens",
        "enabled",
        "perspective_number",
    }
)
_ROUND_KEYS = frozenset({"round_number", "status", "messages", "provider_provenance"})
_PROVIDER_PROVENANCE_KEYS = frozenset(
    {
        "kind",
        "client_id",
        "prompt_id",
        "prompt_label",
        "perspective_number",
        "temperature",
        "host_configuration_id",
        "host_label",
        "api_host",
        "model_id",
    }
)
_MESSAGE_KEYS = frozenset(
    {
        "id",
        "role",
        "content",
        "status",
        "agent_name",
        "theory_label",
        "note",
        "include_in_agent_context",
        "include_note_in_agent_context",
        "client_id",
        "color",
        "agent_index",
        "perspective_number",
        "error",
        "error_code",
        "error_params",
        "usage_available",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "context_usage_available",
        "input_context_tokens",
        "context_window_tokens",
        "context_tokens_exact",
        "omitted_round_numbers",
    }
)


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _require_keys(data: dict[str, Any], required: frozenset[str], name: str) -> None:
    missing = required.difference(data)
    if missing:
        rendered = ", ".join(sorted(missing))
        raise ValueError(f"{name} is missing required fields: {rendered}")


def _require_text(value: Any, name: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be {'a non-empty ' if not allow_empty else 'a '}string")
    return value


def _require_text_fields(data: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    for field_name in fields:
        _require_text(data[field_name], f"{name}.{field_name}")


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _require_optional_text(value: Any, name: str) -> str | None:
    if value is not None:
        return _require_text(value, name)
    return None


def _status(value: Any, name: str, default: str = "completed") -> str:
    value = default if value is None else value
    if value not in {"in_progress", "completed", "interrupted", "failed"}:
        raise ValueError(f"{name} must be in_progress, completed, interrupted, or failed")
    return value


def _require_optional_number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number or null")
    return float(value)


def _require_optional_nonnegative_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or null")
    return value


def _parse_input_values(value: Any) -> dict[str, str]:
    data = _require_mapping(value, "input_values")
    expected = {
        "research_material_context",
        "main_input",
        "additional_instructions",
    }
    if set(data) != expected:
        raise ValueError("input_values must contain the complete current setup fields")
    return {key: _require_text(item, f"input_values.{key}") for key, item in data.items()}


def _parse_input_definitions(value: Any) -> list[dict[str, Any]]:
    from src.prompts.session_types import SessionInputDefinition, validate_session_inputs

    definitions = [
        SessionInputDefinition.model_validate(item)
        for item in _require_list(value, "input_definitions")
    ]
    return [
        item.model_dump(mode="json", exclude_none=True)
        for item in validate_session_inputs(definitions)
    ]


def _parse_synthesis(value: Any) -> dict[str, Any]:
    data = _require_mapping(value, "synthesis")
    _require_keys(data, _SYNTHESIS_KEYS, "synthesis")
    _require_bool(data["enabled"], "synthesis.enabled")
    _require_optional_text(data["api_host"], "synthesis.api_host")
    _require_optional_text(data["llm_id"], "synthesis.llm_id")
    _require_optional_text(data["host_configuration_id"], "synthesis.host_configuration_id")
    _require_optional_text(data["host_label"], "synthesis.host_label")
    _require_optional_number(data["temperature"], "synthesis.temperature")
    return data


def _parse_agent(value: Any) -> StoredAgent:
    data = _require_mapping(value, "agent")
    _require_keys(data, _AGENT_KEYS, "agent")
    max_tokens = _require_optional_nonnegative_int(data["max_tokens"], "agent.max_tokens")
    if max_tokens == 0:
        raise ValueError("agent.max_tokens must be positive when set")
    return StoredAgent(
        name=_require_text(data["name"], "agent.name", allow_empty=False),
        client_id=_require_text(data["client_id"], "agent.client_id", allow_empty=False),
        prompt_id=_require_optional_text(data["prompt_id"], "agent.prompt_id"),
        prompt_label=_require_text(data["prompt_label"], "agent.prompt_label"),
        color=_require_text(data["color"], "agent.color", allow_empty=False),
        temperature=_require_optional_number(data["temperature"], "agent.temperature"),
        llm_id=_require_optional_text(data["llm_id"], "agent.llm_id"),
        api_host=_require_optional_text(data["api_host"], "agent.api_host"),
        host_configuration_id=_require_optional_text(
            data["host_configuration_id"], "agent.host_configuration_id"
        ),
        host_label=_require_optional_text(data["host_label"], "agent.host_label"),
        max_tokens=max_tokens,
        enabled=_require_bool(data["enabled"], "agent.enabled"),
        perspective_number=_required_perspective_number(data["perspective_number"], "agent"),
    )


def _parse_round(value: Any) -> StoredRound:
    data = _require_mapping(value, "round")
    _require_keys(data, _ROUND_KEYS, "round")
    number = _required_perspective_number(data["round_number"], "round")
    return StoredRound(
        round_number=number,
        status=_status(data["status"], "round.status"),
        messages=[
            _parse_message(message) for message in _require_list(data["messages"], "round.messages")
        ],
        provider_provenance=[
            _parse_provider_provenance(item)
            for item in _require_list(data["provider_provenance"], "round.provider_provenance")
        ],
    )


def _parse_provider_provenance(value: Any) -> StoredProviderProvenance:
    data = _require_mapping(value, "provider_provenance")
    _require_keys(data, _PROVIDER_PROVENANCE_KEYS, "provider_provenance")
    kind = _require_text(data["kind"], "provider_provenance.kind", allow_empty=False)
    if kind not in {"perspective", "synthesis"}:
        raise ValueError("provider_provenance.kind must be perspective or synthesis")
    client_id = _require_optional_text(data["client_id"], "provider_provenance.client_id")
    if kind == "perspective" and not client_id:
        raise ValueError("provider_provenance.client_id is required for a perspective")
    if kind == "synthesis" and client_id is not None:
        raise ValueError("provider_provenance.client_id must be null for synthesis")
    perspective_number = data["perspective_number"]
    if kind == "perspective":
        perspective_number = _required_perspective_number(perspective_number, "provider_provenance")
    elif perspective_number is not None:
        raise ValueError("provider_provenance.perspective_number must be null for synthesis")
    return StoredProviderProvenance(
        kind=kind,
        client_id=client_id,
        prompt_id=_require_text(
            data["prompt_id"], "provider_provenance.prompt_id", allow_empty=False
        ),
        prompt_label=_require_text(
            data["prompt_label"], "provider_provenance.prompt_label", allow_empty=False
        ),
        perspective_number=perspective_number,
        temperature=_require_optional_number(
            data["temperature"], "provider_provenance.temperature"
        ),
        host_configuration_id=_require_optional_text(
            data["host_configuration_id"], "provider_provenance.host_configuration_id"
        ),
        host_label=_require_optional_text(data["host_label"], "provider_provenance.host_label"),
        api_host=_require_text(data["api_host"], "provider_provenance.api_host", allow_empty=False),
        model_id=_require_text(data["model_id"], "provider_provenance.model_id", allow_empty=False),
    )


def _parse_message(value: Any) -> StoredMessage:
    data = _require_mapping(value, "message")
    _require_keys(data, _MESSAGE_KEYS, "message")
    role = _require_text(data["role"], "message.role", allow_empty=False)
    if role not in {"user", "agent", "synthesis"}:
        raise ValueError("message.role must be user, agent, or synthesis")
    _require_bool(data["include_in_agent_context"], "message.include_in_agent_context")
    _require_bool(data["include_note_in_agent_context"], "message.include_note_in_agent_context")
    _require_mapping(data["error_params"], "message.error_params")
    omitted = _require_list(data["omitted_round_numbers"], "message.omitted_round_numbers")
    if any(
        isinstance(number, bool) or not isinstance(number, int) or number < 1 for number in omitted
    ):
        raise ValueError("message.omitted_round_numbers must contain positive integers")
    identity = ("agent_name", "color", "agent_index", "perspective_number", "client_id")
    if role == "agent":
        _require_text(data["agent_name"], "message.agent_name", allow_empty=False)
        _require_text(data["color"], "message.color", allow_empty=False)
        _require_optional_nonnegative_int(data["agent_index"], "message.agent_index")
        if data["agent_index"] is None:
            raise ValueError("message.agent_index is required for agent messages")
        _required_perspective_number(data["perspective_number"], "agent message")
        _require_text(data["client_id"], "message.client_id", allow_empty=False)
    elif any(data[field_name] is not None for field_name in identity):
        raise ValueError("non-agent messages must not carry agent identity fields")
    for field_name in ("usage_available", "context_usage_available", "context_tokens_exact"):
        value = data[field_name]
        if value is not None:
            _require_bool(value, f"message.{field_name}")
    for field_name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_context_tokens",
        "context_window_tokens",
    ):
        _require_optional_nonnegative_int(data[field_name], f"message.{field_name}")
    return StoredMessage(
        id=_require_text(data["id"], "message.id", allow_empty=False),
        role=role,
        content=_require_text(data["content"], "message.content"),
        status=_status(data.get("status"), "message.status"),
        agent_name=data["agent_name"],
        theory_label=_require_optional_text(data["theory_label"], "message.theory_label"),
        note=_require_text(data["note"], "message.note"),
        include_in_agent_context=data["include_in_agent_context"],
        include_note_in_agent_context=data["include_note_in_agent_context"],
        client_id=data["client_id"],
        color=data["color"],
        agent_index=data["agent_index"],
        perspective_number=data["perspective_number"],
        error=_require_optional_text(data["error"], "message.error"),
        error_code=_require_optional_text(data["error_code"], "message.error_code"),
        error_params=dict(data["error_params"]),
        usage_available=data["usage_available"],
        prompt_tokens=data["prompt_tokens"],
        completion_tokens=data["completion_tokens"],
        total_tokens=data["total_tokens"],
        context_usage_available=data["context_usage_available"],
        input_context_tokens=data["input_context_tokens"],
        context_window_tokens=data["context_window_tokens"],
        context_tokens_exact=data["context_tokens_exact"],
        omitted_round_numbers=list(omitted),
    )


@dataclass
class StoredDiscussion:
    """Complete discussion in the persisted format."""

    id: str
    created: str
    updated: str
    title: str
    material: str
    initial_question: str
    material_type: str = "document"
    session_type: str = "exploration"
    target_language: str = ""
    prompt_snapshot: StoredPromptSnapshot = field(default_factory=StoredPromptSnapshot)
    session_input_values: dict[str, str] = field(default_factory=dict)
    session_inputs: list[dict[str, Any]] = field(default_factory=list)
    include_unchanged_research_material_context_in_prompt: bool = False
    # Sequential mode is part of the resumable session configuration.
    sequential_mode: bool = False
    is_favorite: bool = False
    synthesis: StoredSynthesisConfig = field(
        default_factory=lambda: StoredSynthesisConfig(
            enabled=False, api_host=None, llm_id=None, temperature=None
        )
    )
    agents: list[StoredAgent] = field(default_factory=list)
    rounds: list[StoredRound] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert the snapshot into its JSON representation."""
        return {
            "id": self.id,
            "created": self.created,
            "updated": self.updated,
            "title": self.title,
            "material": self.material,
            "initial_question": self.initial_question,
            "material_type": self.material_type,
            "session_type": self.session_type,
            "target_language": self.target_language,
            "prompt_snapshot": self.prompt_snapshot.to_dict(),
            "input_values": dict(self.session_input_values),
            "input_definitions": list(self.session_inputs),
            "include_unchanged_research_material_context_in_prompt": bool(
                self.include_unchanged_research_material_context_in_prompt
            ),
            "sequential_mode": bool(self.sequential_mode),
            "is_favorite": bool(self.is_favorite),
            "synthesis": {
                "enabled": bool(self.synthesis.enabled),
                "api_host": self.synthesis.api_host,
                "llm_id": self.synthesis.llm_id,
                "host_configuration_id": self.synthesis.host_configuration_id,
                "host_label": self.synthesis.host_label,
                "temperature": self.synthesis.temperature,
            },
            "agents": [
                {
                    "name": a.name,
                    "client_id": a.client_id,
                    "prompt_id": a.prompt_id,
                    "prompt_label": a.prompt_label,
                    "color": a.color,
                    # JSON null preserves the absence of a temperature override.
                    "temperature": a.temperature,
                    "llm_id": a.llm_id,
                    "api_host": a.api_host,
                    "host_configuration_id": a.host_configuration_id,
                    "host_label": a.host_label,
                    "max_tokens": a.max_tokens,
                    # The editable roster toggle must round-trip as a JSON boolean.
                    "enabled": bool(a.enabled),
                    "perspective_number": int(a.perspective_number or 0),
                    # API keys are never part of the persisted schema.
                }
                for a in self.agents
            ],
            "rounds": [
                {
                    "round_number": r.round_number,
                    "status": r.status,
                    "provider_provenance": [
                        {
                            "kind": provider.kind,
                            "client_id": provider.client_id,
                            "prompt_id": provider.prompt_id,
                            "prompt_label": provider.prompt_label,
                            "perspective_number": provider.perspective_number,
                            "temperature": provider.temperature,
                            "host_configuration_id": provider.host_configuration_id,
                            "host_label": provider.host_label,
                            "api_host": provider.api_host,
                            "model_id": provider.model_id,
                        }
                        for provider in r.provider_provenance
                    ],
                    "messages": [
                        {
                            "id": m.id,
                            "role": m.role,
                            "content": m.content,
                            "status": m.status,
                            "agent_name": m.agent_name,
                            "theory_label": m.theory_label,
                            "note": m.note,
                            "include_in_agent_context": bool(m.include_in_agent_context),
                            "include_note_in_agent_context": bool(m.include_note_in_agent_context),
                            "client_id": m.client_id,
                            "color": m.color,
                            "agent_index": m.agent_index,
                            "perspective_number": m.perspective_number,
                            "error": m.error,
                            "error_code": m.error_code,
                            "error_params": dict(m.error_params),
                            "usage_available": m.usage_available,
                            "prompt_tokens": m.prompt_tokens,
                            "completion_tokens": m.completion_tokens,
                            "total_tokens": m.total_tokens,
                            "context_usage_available": m.context_usage_available,
                            "input_context_tokens": m.input_context_tokens,
                            "context_window_tokens": m.context_window_tokens,
                            "context_tokens_exact": m.context_tokens_exact,
                            "omitted_round_numbers": list(m.omitted_round_numbers),
                        }
                        for m in r.messages
                    ],
                }
                for r in self.rounds
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredDiscussion:
        """Parse one complete, current discussion snapshot.

        Persisted sessions are immutable snapshots, not an interchange format.
        Reject incomplete payloads rather than fabricating snapshot data.
        """
        _require_mapping(data, "discussion")
        _require_keys(data, _DISCUSSION_KEYS, "discussion")
        _require_text_fields(
            data,
            (
                "id",
                "created",
                "updated",
                "title",
                "material",
                "initial_question",
                "material_type",
                "session_type",
                "target_language",
            ),
            "discussion",
        )
        _require_bool(
            data["include_unchanged_research_material_context_in_prompt"],
            "discussion.include_unchanged_research_material_context_in_prompt",
        )
        _require_bool(data["sequential_mode"], "discussion.sequential_mode")
        _require_bool(data["is_favorite"], "discussion.is_favorite")
        input_values = _parse_input_values(data["input_values"])
        input_definitions = _parse_input_definitions(data["input_definitions"])
        synthesis_data = _parse_synthesis(data["synthesis"])
        return cls(
            id=data["id"],
            created=data["created"],
            updated=data["updated"],
            title=data["title"],
            material=data["material"],
            initial_question=data["initial_question"],
            material_type=data["material_type"],
            session_type=data["session_type"],
            target_language=data["target_language"],
            prompt_snapshot=StoredPromptSnapshot.from_dict(data["prompt_snapshot"]),
            session_input_values=input_values,
            session_inputs=input_definitions,
            include_unchanged_research_material_context_in_prompt=data[
                "include_unchanged_research_material_context_in_prompt"
            ],
            sequential_mode=data["sequential_mode"],
            is_favorite=data["is_favorite"],
            synthesis=StoredSynthesisConfig(
                enabled=synthesis_data["enabled"],
                api_host=synthesis_data["api_host"],
                llm_id=synthesis_data["llm_id"],
                host_configuration_id=synthesis_data["host_configuration_id"],
                host_label=synthesis_data["host_label"],
                temperature=synthesis_data["temperature"],
            ),
            agents=[_parse_agent(agent) for agent in _require_list(data["agents"], "agents")],
            rounds=[
                _parse_round(round_data) for round_data in _require_list(data["rounds"], "rounds")
            ],
        )

    @staticmethod
    def _append_message_context_status(
        lines: list[str], message: StoredMessage, copy: dict[str, str]
    ) -> None:
        if not message.include_in_agent_context:
            lines.extend(("", f"> **{copy['context_status']}:** {copy['excluded_from_context']}"))

    @classmethod
    def _append_markdown_message(
        cls, lines: list[str], message: StoredMessage, copy: dict[str, str]
    ) -> None:
        """Append one stored message and its immutable audit metadata."""

        lines.extend(("---", ""))
        if message.role == "synthesis":
            lines.extend((f"#### ✦ {copy['synthesis']}", "", message.content))
            if message.status != "completed":
                status_label = copy["round_status"].get(message.status, message.status)
                lines.extend(("", f"> **{copy['status']}:** {status_label}"))
            if message.error:
                lines.extend(("", f"> **Error:** {message.error}"))
            lines.append("")
            return
        if message.role == "user":
            header = f"#### 👤 {copy['moderator']}"
        else:
            perspective = (
                f"Perspective {message.perspective_number}"
                if message.perspective_number
                else (message.agent_name or "Perspective")
            )
            header = f"#### 🎭 {perspective}"
            if message.theory_label:
                header += f": {message.theory_label}"
        lines.extend((header, "", message.content))
        if message.status != "completed":
            status_label = copy["round_status"].get(message.status, message.status)
            lines.extend(("", f"> **{copy['status']}:** {status_label}"))
        cls._append_message_context_status(lines, message, copy)
        if message.note.strip():
            lines.extend(("", f"**{copy['message_note']}:**", "", message.note))
        lines.append("")

    def _append_markdown_rounds(self, lines: list[str], copy: dict[str, str]) -> None:
        """Append discussion rounds in their persisted order."""

        lines.extend((f"## {copy['discussion']}", ""))
        for round_data in self.rounds:
            lines.extend((f"### {copy['round']} {round_data.round_number}", ""))
            if round_data.status != "completed":
                status_label = copy["round_status"].get(round_data.status, round_data.status)
                lines.extend((f"> **{copy['status']}:** {status_label}", ""))
            if round_data.provider_provenance:
                lines.extend((f"#### {copy['round_configuration']}", ""))
                for provider in round_data.provider_provenance:
                    subject = (
                        f"{copy['perspective']} {provider.perspective_number}"
                        if provider.kind == "perspective"
                        else copy["synthesis"]
                    )
                    details = [
                        f"{copy['role']}: {provider.prompt_label} (`{provider.prompt_id}`)",
                    ]
                    if provider.temperature is not None:
                        details.append(f"{copy['temperature']} {provider.temperature:g}")
                    details.extend(
                        (
                            f"{copy['host']}: {provider.host_label or provider.host_configuration_id or '?'}",
                            f"{copy['model']}: {provider.model_id}",
                        )
                    )
                    lines.append(f"- **{subject}:** " + " · ".join(details))
                lines.append("")
            for message in round_data.messages:
                self._append_markdown_message(lines, message, copy)

    @staticmethod
    def _append_markdown_block(
        lines: list[str], title: str, content: str, *, level: int = 3
    ) -> None:
        longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
        fence = "`" * max(3, longest + 1)
        lines.extend((f"{'#' * level} {title}", "", f"{fence}text", content, fence, ""))

    @staticmethod
    def _prompt_section(prompt: str, heading: str) -> str:
        """Read one assembled section without recreating its instruction text."""

        match = re.search(rf"(?m)^{re.escape(heading)}(?:\n|$)", prompt)
        if match is None:
            return ""
        next_heading = re.search(r"(?m)^=== .+ ===(?:\n|$)", prompt[match.end() :])
        end = match.end() + next_heading.start() if next_heading else len(prompt)
        return prompt[match.start() : end].strip()

    @staticmethod
    def _append_ordered_instruction(
        lines: list[str], number: int, label: str, text: str = ""
    ) -> None:
        lines.extend((f"{number}. {label}", ""))
        if text:
            StoredDiscussion._append_indented_block(lines, text)

    @staticmethod
    def _append_indented_block(lines: list[str], text: str) -> None:
        longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
        fence = "`" * max(3, longest + 1)
        lines.extend(
            (f"   {fence}text", *(f"   {line}" for line in text.splitlines()), f"   {fence}", "")
        )

    @classmethod
    def _append_current_prompt_organization(
        cls, lines: list[str], locale: str, prompt_documentation: list[tuple[str, str, str]]
    ) -> None:
        perspective = next(
            (item for item in prompt_documentation if item[0].startswith("Perspective ")), None
        )
        synthesis = next(
            (item for item in prompt_documentation if item[0] == "Round Synthesis"), None
        )
        if perspective is None:
            return
        system, user = perspective[1:]
        de = locale == "de"
        lines.extend(
            (
                "### Aktuelle Prompt-Reihenfolge" if de else "### Current Prompt Organization",
                "",
                "Diese Reihenfolge folgt der aktuellen Assemblierung. Gespeicherte Definitionen oben können aus einer älteren Version stammen."
                if de
                else "This order follows current assembly. Saved definitions above may come from an older version.",
                "",
                "#### Perspektiven-Prompting" if de else "#### Perspective Prompting",
                "",
                "##### Systemnachricht" if de else "##### System Message",
                "",
            )
        )
        system_steps = [
            ("Diskussionsrahmen" if de else "Discussion setting", ""),
            ("Session-Kontext (falls vorhanden)" if de else "Session context (when present)", ""),
            ("Forschungsauftrag (falls vorhanden)" if de else "Research task (when present)", ""),
            ("Session-Vorgaben (falls vorhanden)" if de else "Session guidance (when present)", ""),
            ("Gemeinsame Anweisungen" if de else "Shared instructions", ""),
            (
                "Regel für Forschenden-Notizen (gilt für alle Perspektiven)"
                if de
                else "Researcher-note rule (applies across perspectives)",
                cls._prompt_section(system, "=== RESEARCHER NOTES ==="),
            ),
            ("Perspektiven-Definition" if de else "Perspective definition", ""),
            (
                "Abschließende Sprachvorgabe (gilt für alle Perspektiven)"
                if de
                else "Final language requirement (applies across perspectives)",
                cls._prompt_section(system, "=== FINAL RESPONSE LANGUAGE REQUIREMENT ==="),
            ),
        ]
        for number, (label, instruction) in enumerate(system_steps, 1):
            cls._append_ordered_instruction(lines, number, label, instruction)
        lines.extend(("##### User-Nachricht" if de else "##### User Message", ""))
        user_steps = [
            (
                "Forschungsmaterial (falls vorhanden)"
                if de
                else "Research material (when present)",
                "",
            ),
            (
                "Einbezogener Diskussionsverlauf; Notizen stehen bei der zugehörigen Perspektiven-Antwort"
                if de
                else "Included transcript; notes remain beside their Perspective response",
                "",
            ),
            ("Aktuelle Eingabe der moderierenden Person" if de else "Current moderator input", ""),
        ]
        for number, (label, instruction) in enumerate(user_steps, 1):
            cls._append_ordered_instruction(lines, number, label, instruction)
        lines.append(
            "4. Bedingte Erinnerung an Forschenden-Notizen (gilt für alle Perspektiven)"
            if de
            else "4. Conditional researcher-note reminder (applies across perspectives)"
        )
        lines.extend(
            (
                "",
                "   Nur wenn der einbezogene Kontext eine aktiv einbezogene, nicht leere Notiz an einer Perspektiven-Antwort aus der unmittelbar vorherigen Runde enthält. `{N}` ist deren Rundennummer."
                if de
                else "   Included only when the selected context contains a nonempty, opted-in note on an included Perspective response from the immediately preceding round. `{N}` is that round's number.",
                "",
            )
        )
        cls._append_indented_block(
            lines, f"{RESEARCHER_NOTE_REMINDER_HEADING}\n{RESEARCHER_NOTE_REMINDER_TEXT}"
        )
        cls._append_ordered_instruction(
            lines,
            5,
            "Abschließende Spracherinnerung (gilt für alle Perspektiven)"
            if de
            else "Final language reminder (applies across perspectives)",
            cls._prompt_section(user, "=== CURRENT RESPONSE LANGUAGE REMINDER ==="),
        )
        if synthesis:
            synthesis_system, synthesis_user = synthesis[1:]
            lines.extend(
                (
                    "#### Synthese-Prompting" if de else "#### Synthesis Prompting",
                    "",
                    "##### Systemnachricht" if de else "##### System Message",
                    "",
                )
            )
            cls._append_ordered_instruction(
                lines,
                1,
                "Gespeicherte Synthese-Anweisungen" if de else "Saved synthesis instructions",
            )
            cls._append_ordered_instruction(
                lines,
                2,
                "Abschließende Sprachvorgabe" if de else "Final language requirement",
                cls._prompt_section(
                    synthesis_system, "=== FINAL RESPONSE LANGUAGE REQUIREMENT ==="
                ),
            )
            lines.extend(("##### User-Nachricht" if de else "##### User Message", ""))
            cls._append_ordered_instruction(
                lines, 1, "Orientierung zur Session" if de else "Session orientation"
            )
            cls._append_ordered_instruction(
                lines,
                2,
                "Aktuelle Frage und Beiträge dieser Runde"
                if de
                else "Current question and this round's contributions",
            )
            cls._append_ordered_instruction(
                lines,
                3,
                "Abschließende Spracherinnerung" if de else "Final language reminder",
                cls._prompt_section(synthesis_user, "=== CURRENT RESPONSE LANGUAGE REMINDER ==="),
            )

    def _append_markdown_snapshot(
        self, lines: list[str], locale: str, prompt_documentation: list[tuple[str, str, str]]
    ) -> None:
        """Append frozen prompt assets and optional current-state reconstruction."""

        snapshot = self.prompt_snapshot
        if snapshot.is_empty:
            return
        labels = (
            (
                "Orchestration System",
                "Saved Prompt Definitions",
                "Shared Instructions",
                "Perspective Prompts",
                "Synthesis Guidance",
            )
            if locale == "en"
            else (
                "Orchestrierungssystem",
                "Gespeicherte Prompt-Definitionen",
                "Gemeinsame Anweisungen",
                "Perspektiven-Prompts",
                "Synthese-Leitfaden",
            )
        )
        lines.extend((f"## {labels[0]}", ""))
        lines.extend((f"### {labels[1]}", ""))
        lines.append(
            "These definitions were saved when the discussion began. They may differ from current rules and the reconstructed messages below."
            if locale == "en"
            else "Diese Definitionen wurden beim Beginn der Diskussion gespeichert. Sie können von aktuellen Regeln und den unten rekonstruierten Nachrichten abweichen."
        )
        lines.append("")
        used_globals = [
            block
            for block in snapshot.globals
            if block.get("id") in snapshot.used_global_ids and isinstance(block.get("content"), str)
        ]
        if used_globals:
            lines.extend((f"#### {labels[2]}", ""))
            for block in used_globals:
                self._append_markdown_block(
                    lines, str(block.get("label") or block["id"]), block["content"], level=5
                )
        used_role_ids = set(snapshot.used_role_ids)
        used_role_ids.update(
            provider.prompt_id
            for round_data in self.rounds
            for provider in round_data.provider_provenance
            if provider.kind == "perspective"
        )
        used_roles = [role for role in snapshot.roles if role.get("id") in used_role_ids]
        if used_roles:
            lines.extend((f"#### {labels[3]}", ""))
            for role in used_roles:
                parts = [
                    f"{name.upper()}:\n{role[name]}"
                    for name in ("role", "task", "output_format")
                    if isinstance(role.get(name), str) and role[name]
                ]
                if parts:
                    self._append_markdown_block(
                        lines, str(role.get("label") or role["id"]), "\n\n".join(parts), level=5
                    )
        if snapshot.synthesis_used and snapshot.synthesis:
            lines.extend((f"#### {labels[4]}", ""))
            self._append_markdown_block(
                lines,
                str(snapshot.synthesis.get("label") or labels[4]),
                str(snapshot.synthesis.get("content") or ""),
                level=5,
            )
        if prompt_documentation:
            self._append_current_prompt_organization(lines, locale, prompt_documentation)
            lines.append(
                "### Current-State Prompt Reconstruction"
                if locale == "en"
                else "### Prompt-Rekonstruktion des aktuellen Zustands"
            )
            lines.append("")
            lines.append(
                "The following messages are reconstructed from the current discussion state and "
                "current assembly code. They are not recorded historical requests and do not "
                "establish what was sent in earlier rounds."
                if locale == "en"
                else "Die folgenden Nachrichten wurden aus dem aktuellen Diskussionszustand und "
                "dem aktuellen Prompt-Code rekonstruiert. Sie sind keine aufgezeichneten "
                "historischen Anfragen und belegen nicht, was in früheren Runden gesendet wurde."
            )
            lines.append("")
            for label, system_prompt, user_prompt in prompt_documentation:
                lines.extend((f"#### {label}", ""))
                self._append_markdown_block(
                    lines,
                    "System Message" if locale == "en" else "Systemnachricht",
                    system_prompt,
                    level=5,
                )
                if user_prompt:
                    self._append_markdown_block(
                        lines,
                        "User Message" if locale == "en" else "User-Nachricht",
                        user_prompt,
                        level=5,
                    )

    def to_markdown(
        self, locale: str = "de", prompt_documentation: list[tuple[str, str, str]] | None = None
    ) -> str:
        """Export the discussion as formatted Markdown.

        The fixed export shell follows ``locale``; stored and authored content
        remains verbatim so exporting never changes research data.

        """
        try:
            copy = _EXPORT_COPY[locale]
        except KeyError as exc:
            raise ValueError(f"Unsupported export locale: {locale}") from exc

        lines = []

        lines.append(f"# {self.title}")
        lines.append("")

        created_dt = self.created[:16].replace("T", " ") if self.created else "?"
        if locale == "en" and self.created:
            try:
                created_dt = datetime.fromisoformat(self.created.replace("Z", "+00:00")).strftime(
                    "%m/%d/%Y %H:%M"
                )
            except ValueError:
                pass
        lines.append(f"**{copy['created']}:** {created_dt}  ")
        lines.append(f"**{copy['rounds']}:** {len(self.rounds)}  ")
        lines.append(f"**{copy['session_type']}:** {self.session_type}  ")
        lines.append(f"**{copy['material_type']}:** {self.material_type}  ")
        lines.append("")

        lines.append(f"## {copy['analysis_context']}")
        lines.append("")

        for raw_definition in self.session_inputs:
            try:
                label = raw_definition["label"]
                key = str(raw_definition["key"])
            except (AttributeError, KeyError, ValueError):
                continue
            if not isinstance(label, str):
                continue
            value = effective_session_input_value(
                key,
                self.session_input_values.get(key, ""),
                raw_definition.get("default_text"),
                self.include_unchanged_research_material_context_in_prompt,
            )
            if value or raw_definition.get("required", False):
                lines.append(f"### {label}")
                lines.append("")
                lines.append(value or f"*{copy['missing_value']}*")
                lines.append("")

        if self.agents:
            lines.append(f"## {copy['perspectives']}")
            lines.append("")
            for agent in self.agents:
                # Omit temperature when the provider controls its default.
                if agent.temperature is not None:
                    temp_str = f" ({copy['temperature']} {agent.temperature:.1f})"
                else:
                    temp_str = ""
                perspective = (
                    f"Perspective {agent.perspective_number}"
                    if agent.perspective_number
                    else agent.name
                )
                lines.append(f"- **{perspective}**: {agent.prompt_label}{temp_str}")
            lines.append("")

        lines.append(f"## {copy['material']}")
        lines.append("")
        if self.material:
            for line in self.material.split("\n"):
                lines.append(f"> {line}")
        else:
            lines.append(f"*{copy['missing_material']}*")
        lines.append("")

        lines.append(f"## {copy['initial_instruction']}")
        lines.append("")
        startauftrag = self.initial_question.strip()
        if startauftrag:
            lines.append(f"**{startauftrag}**")
        else:
            lines.append(f"*{copy['missing_value']}*")
        lines.append("")

        self._append_markdown_rounds(lines, copy)

        self._append_markdown_snapshot(lines, locale, prompt_documentation or [])

        lines.append("---")
        lines.append("")
        lines.append(f"*{copy['footer']} | ID: {self.id[:8]}*")

        return "\n".join(lines)


class DiscussionStorage:
    """Persist and load canonical discussion snapshots as atomic JSON files."""

    def __init__(self, storage_dir: Path | str):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_tmp_files()
        logger.info(f"DiscussionStorage initialisiert: {self.storage_dir}")

    def _cleanup_stale_tmp_files(self) -> None:
        """Remove temp files abandoned before their atomic replacement."""
        for tmp_file in self.storage_dir.glob("*.json.tmp"):
            try:
                tmp_file.unlink()
            except OSError as exc:
                logger.warning(f"Konnte stale tmp-Datei nicht löschen: {tmp_file}: {exc}")

    def _generate_filename(self, discussion: StoredDiscussion) -> str:
        """Generate a filename from the creation time and id prefix."""
        timestamp = datetime.fromisoformat(discussion.created)
        time_part = timestamp.strftime("%Y-%m-%d_%H-%M")
        id_short = discussion.id[:8]
        return f"{time_part}_{id_short}.json"

    def file_id_for(self, discussion: StoredDiscussion) -> str:
        """Return the canonical filename stem for a stored discussion."""
        return self._generate_filename(discussion).removesuffix(".json")

    def _sanitize_title(self, title: str) -> str:
        """Sanitize an optional human-readable filename suffix."""
        sanitized = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß\s-]", "", title)
        sanitized = re.sub(r"\s+", "-", sanitized.strip())
        return sanitized[:30]

    def create_new(self, title: str = "") -> StoredDiscussion:
        """Create an empty discussion snapshot."""
        now = datetime.now().isoformat()
        return StoredDiscussion(
            id=str(uuid.uuid4()),
            created=now,
            updated=now,
            title=title or "Unbenannte Diskussion",
            material="",
            initial_question="",
        )

    @_serializes_mutable_data
    def save(self, discussion: StoredDiscussion) -> Path:
        """Persist a discussion atomically so readers never observe a partial file."""
        discussion.updated = datetime.now().isoformat()

        filename = self._generate_filename(discussion)
        filepath = self.storage_dir / filename
        payload = discussion.to_dict()

        self._atomic_write_json(filepath, payload)

        logger.info(f"Diskussion gespeichert: {filepath}")
        return filepath

    def _atomic_write_json(self, filepath: Path, payload: dict[str, Any]) -> None:
        """Atomically write ``payload`` as JSON to ``filepath``.

        Writes to a sibling ``.json.tmp`` file in the same directory
        and then ``os.replace``s it into place so readers always see
        either the old content or the new content — never a partial
        write.  On any error the temp file is removed before the
        exception propagates, and the existing canonical file (if
        any) is left intact because ``os.replace`` happens only
        after a successful write.
        """
        tmp_path = filepath.with_suffix(filepath.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(
                    payload,
                    f,
                    ensure_ascii=False,  # Preserve Unicode content verbatim.
                    indent=2,
                )
            os.replace(tmp_path, filepath)
        except BaseException:
            # Best-effort cleanup; do not mask the original error.
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

    def load(self, file_id: str) -> StoredDiscussion | None:
        """Load a discussion by its exact canonical file ID."""
        filepath = self.resolve_file_id(file_id)
        if filepath is not None:
            return self._load_file(filepath)
        return None

    def load_by_path(self, filepath: Path | str) -> StoredDiscussion | None:
        """Load a discussion from one explicit path."""
        return self._load_file(Path(filepath))

    def resolve_file_id(self, file_id: str) -> Path | None:
        """Resolve an exact, safe file-id to its absolute JSON path.

        The id is the exact filename *stem* (the part before ``.json``)
        and must satisfy two invariants:

        1. It must contain **no** path separators, no parent-directory
           references, and no leading dots — i.e. it must be safe to
           join onto the storage directory without escaping it.
        2. The corresponding ``<stem>.json`` must exist inside the
           storage directory.

        Returns the absolute path on success, ``None`` if no such file
        exists.  Raises :class:`ValueError` for any unsafe id so the
        caller cannot accidentally treat a user-supplied id as a path.
        """
        if not isinstance(file_id, str):
            raise ValueError("file_id must be a string")
        if (
            not file_id
            or not _FILENAME_STEM_PATTERN.match(file_id)
            or file_id in (".", "..")
            or file_id.startswith(".")
        ):
            raise ValueError(f"unsafe file_id: {file_id!r}")

        candidate = (self.storage_dir / f"{file_id}.json").resolve()
        storage_root = self.storage_dir.resolve()
        try:
            candidate.relative_to(storage_root)
        except ValueError as exc:
            # Resolve containment again to reject symlink-based path escape.
            raise ValueError(f"file_id escapes storage directory: {file_id!r}") from exc

        if not candidate.is_file():
            return None
        return candidate

    def _load_file(self, filepath: Path) -> StoredDiscussion | None:
        """Load and validate one JSON discussion file."""
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"Diskussion geladen: {filepath}")
            return StoredDiscussion.from_dict(data)
        except Exception as e:
            logger.error(f"Fehler beim Laden von {filepath}: {e}")
            return None

    def list_all(self) -> list[dict[str, Any]]:
        """Return canonical, path-free metadata for every stored discussion."""
        summaries: list[dict[str, Any]] = []

        for filepath in sorted(self.storage_dir.glob("*.json"), reverse=True):
            try:
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                created = data.get("created", "")
                updated = data.get("updated") or created
                file_id = filepath.stem
                summaries.append(
                    {
                        "file_id": file_id,
                        "title": data.get("title", "Unbenannt"),
                        "created": created,
                        "updated": updated,
                        "session_type": data["session_type"],
                        "round_count": len(data.get("rounds", [])),
                        "is_favorite": bool(data.get("is_favorite", False)),
                    }
                )
            except Exception as e:
                logger.warning(f"Konnte {filepath} nicht lesen: {e}")

        return summaries

    def sessions_referencing_host(
        self, host_configuration_id: str, api_host: str
    ) -> list[dict[str, str]]:
        """Return path-free identities retaining one exact host identity."""
        normalized_host = api_host.rstrip("/")
        dependencies: list[dict[str, str]] = []
        for filepath in sorted(self.storage_dir.glob("*.json"), reverse=True):
            stored = self._load_file(filepath)
            if stored is None:
                continue
            current_reference = any(
                agent.host_configuration_id == host_configuration_id
                and (agent.api_host or "").rstrip("/") == normalized_host
                for agent in stored.agents
            ) or (
                stored.synthesis.host_configuration_id == host_configuration_id
                and (stored.synthesis.api_host or "").rstrip("/") == normalized_host
            )
            historical_reference = any(
                provider.host_configuration_id == host_configuration_id
                and provider.api_host.rstrip("/") == normalized_host
                for round_data in stored.rounds
                for provider in round_data.provider_provenance
            )
            if current_reference or historical_reference:
                dependencies.append({"file_id": filepath.stem, "title": stored.title})
        return dependencies

    @_serializes_mutable_data
    def delete(self, file_id: str) -> bool:
        """Delete one discussion identified by its exact canonical file ID."""
        filepath = self.resolve_file_id(file_id)

        if filepath is not None and filepath.exists():
            filepath.unlink()
            logger.info(f"Diskussion gelöscht: {filepath}")
            return True

        return False

    @_serializes_mutable_data
    def delete_many_transactional(self, file_ids: list[str]) -> list[str]:
        """Remove exact IDs through a same-filesystem staging transaction."""
        unique_ids = list(dict.fromkeys(file_ids))
        paths: list[tuple[str, Path]] = []
        for file_id in unique_ids:
            filepath = self.resolve_file_id(file_id)
            if filepath is None:
                raise FileNotFoundError("session catalogue changed")
            paths.append((file_id, filepath))

        staging = self.storage_dir / f".session-delete-{uuid.uuid4().hex}"
        staging.mkdir()
        moved: list[tuple[str, Path, Path]] = []
        try:
            for file_id, source in paths:
                staged = staging / source.name
                os.replace(source, staged)
                moved.append((file_id, source, staged))
        except OSError as original_error:
            rollback_failed = False
            for _file_id, source in reversed(paths):
                staged = staging / source.name
                if not staged.is_file():
                    continue
                try:
                    os.replace(staged, source)
                except OSError:
                    rollback_failed = True
            try:
                staging.rmdir()
            except OSError:
                pass
            if rollback_failed:
                deleted_ids = [file_id for file_id, source in paths if not source.is_file()]
                retained_ids = [file_id for file_id, source in paths if source.is_file()]
                raise SessionDeletionRollbackError(deleted_ids, retained_ids) from original_error
            raise

        for _file_id, _source, staged in moved:
            try:
                staged.unlink()
            except OSError:
                logger.warning("Committed session deletion left recoverable staged data")
        try:
            staging.rmdir()
        except OSError:
            pass
        return unique_ids

    @_serializes_mutable_data
    def rename(self, file_id: str, new_title: str) -> bool:
        """Update only the ``title`` metadata of a stored discussion.

        The canonical filename and ``file_id`` remain unchanged. This keeps
        autosaves, file locks, and frontend references stable while the title
        changes.

        Args:
            file_id: Canonical safe file ID (exact stem).
            new_title: New display title. Empty or whitespace-only values are
                rejected.

        Returns:
            ``True`` on success and ``False`` when the file does not exist.
            Unsafe IDs raise :class:`ValueError`.
        """
        new_title = (new_title or "").strip()
        if not new_title:
            raise ValueError("new_title must be a non-empty string")

        filepath = self.resolve_file_id(file_id)
        if filepath is None:
            return False

        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Rename: konnte {filepath} nicht lesen: {e}")
            return False

        data["title"] = new_title
        data["updated"] = datetime.now().isoformat()

        self._atomic_write_json(filepath, data)

        logger.info(f"Diskussion umbenannt (metadata only): {filepath.name} → {new_title!r}")
        return True

    @_serializes_mutable_data
    def set_favorite(self, file_id: str, is_favorite: bool) -> bool:
        """Update only the ``is_favorite`` flag of a stored discussion.

        The canonical filename and ``file_id`` remain unchanged, keeping
        autosaves, file locks, and frontend references stable.

        Only ``is_favorite`` is changed. In particular, ``updated`` remains
        unchanged so a favorite toggle does not move the session in
        date-sorted or ordered listings. The exact file ID is resolved through
        ``resolve_file_id`` without prefix matching.

        Args:
            file_id: Canonical safe file ID (exact stem).
            is_favorite: New boolean value.

        Returns:
            ``True`` on success and ``False`` when the file does not exist.
            Unsafe IDs raise :class:`ValueError`.
        """
        filepath = self.resolve_file_id(file_id)
        if filepath is None:
            return False

        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"set_favorite: konnte {filepath} nicht lesen: {e}")
            return False

        data["is_favorite"] = bool(is_favorite)
        # Favorites are non-recency metadata and must not affect date sorting.

        self._atomic_write_json(filepath, data)

        logger.info(
            f"Diskussion-Favorit gesetzt (metadata only): {filepath.name} → {bool(is_favorite)}"
        )
        return True

    def session_path_for_reveal(self, file_id: str) -> Path | None:
        """Resolve the exact stored-session path for an existing safe file id."""
        return self.resolve_file_id(file_id)

    def export_markdown(self, discussion: StoredDiscussion, filepath: Path | str) -> Path:
        """Export a discussion as a Markdown file.

        Args:
            discussion: Discussion to export.
            filepath: Destination path for the Markdown file.

        Returns:
            Path to the created file.
        """
        filepath = Path(filepath)

        if filepath.suffix.lower() != ".md":
            filepath = filepath.with_suffix(".md")

        markdown_content = discussion.to_markdown()

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        logger.info(f"Diskussion als Markdown exportiert: {filepath}")
        return filepath
