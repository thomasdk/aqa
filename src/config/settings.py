"""Application configuration and persisted LLM host preferences."""

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings

from src.config.user_data import (
    mutable_data_lock,
    prompt_defaults_dir,
    prompt_library_dir,
    settings_path,
)
from src.local_ai.catalog import MODELS

LOCAL_AI_HOST_LABEL = "Lokale KI"
LOCAL_AI_HOST_KIND = "local_ai"
LOCAL_AI_HOST_URL = "http://127.0.0.1:8080"
# Must match llama.cpp's public aliases (see ``ModelSpec.api_alias``).
LOCAL_AI_MODEL_ALIASES = tuple(model.api_alias for model in MODELS.values())
DEFAULT_LOCAL_AI_CONTEXT_TOKENS = 32_768


class LLMHostConfig(TypedDict, total=False):
    """Documented shape of one configured LLM host.

    ``model`` is the preferred model and ``models`` contains the selectable
    models offered by the host.  ``kind`` is deliberately non-secret metadata;
    the ``local_ai`` value identifies the application-managed Local AI host.
    ``is_favorite`` marks the single preferred *external* host; at most one
    external host may have it set to ``True`` after normalization.  The
    application-managed Local AI host is selected separately and never carries
    that global preference marker. Additional keys remain allowed at runtime
    and are preserved by normalization.
    """

    __pydantic_config__ = ConfigDict(extra="allow")

    url: str
    api_key: str
    model: str
    models: list[str]
    kind: str
    is_favorite: bool
    context_tokens: int


def _local_ai_host() -> dict[str, Any]:
    """Return a fresh copy of the single built-in Local AI host."""
    return {
        "url": LOCAL_AI_HOST_URL,
        "api_key": "",
        "model": LOCAL_AI_MODEL_ALIASES[0],
        "models": list(LOCAL_AI_MODEL_ALIASES),
        "kind": LOCAL_AI_HOST_KIND,
    }


def _is_valid_managed_local_ai_entry(entry: Any) -> bool:
    """Whether a marked managed entry still satisfies the Local AI boundary."""
    if not isinstance(entry, Mapping):
        return False
    if entry.get("kind") != LOCAL_AI_HOST_KIND:
        return False
    if not _is_managed_local_ai_url(entry.get("url")):
        return False
    if entry.get("api_key") not in (None, ""):
        return False
    model = entry.get("model")
    if model not in LOCAL_AI_MODEL_ALIASES:
        return False
    models = entry.get("models")
    if not isinstance(models, (list, tuple)):
        return False
    # Normalization keeps the preferred model first. Require exactly the
    # supported aliases, without duplicates, and the declared preference first.
    return list(models) == [model, *(alias for alias in LOCAL_AI_MODEL_ALIASES if alias != model)]


def _is_managed_local_ai_url(value: Any) -> bool:
    """Accept only the app-owned HTTP loopback endpoint, including a fallback port."""
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.username is None
        and parsed.password is None
        and isinstance(port, int)
        and 1 <= port <= 65535
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def _clean_model_name(value: Any) -> str | None:
    """Return a normalized model name, ignoring non-string/empty values."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name or None


def _normalize_host_entry(raw_entry: Any) -> dict[str, Any]:
    """Normalize one host while preserving unrecognized provider keys."""
    entry = dict(raw_entry) if isinstance(raw_entry, Mapping) else {}

    favorite = entry.get("is_favorite")
    if favorite is True:
        entry["is_favorite"] = True
    else:
        entry.pop("is_favorite", None)

    preferred = _clean_model_name(entry.get("model"))
    raw_models = entry.get("models")
    if isinstance(raw_models, str):
        raw_models = [raw_models]
    if not isinstance(raw_models, (list, tuple)):
        raw_models = []

    models: list[str] = []
    if preferred is not None:
        models.append(preferred)
    for raw_model in raw_models:
        model = _clean_model_name(raw_model)
        if model is not None and model not in models:
            models.append(model)

    entry["models"] = models
    if models:
        entry["model"] = models[0]
    else:
        entry.pop("model", None)
    return entry


def normalize_known_llm_hosts(hosts: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Normalize known hosts for loading and persistence.

    Model names are stripped, empty names removed, duplicates collapsed, and
    the preferred ``model`` is kept first. Unknown host forms remain custom
    hosts and are neither adopted nor replaced.

    ``is_favorite`` is only preserved for the first external host in insertion
    order that carries the exact boolean value ``true``; every other host has
    the field cleared. The managed Local AI entry never has this marker.

    The reserved ``Lokale KI`` label is only treated as application-managed
    when it carries a valid managed marker. A same-label custom host is left
    unmarked and is never silently converted or overwritten.
    """
    source = hosts if isinstance(hosts, Mapping) else {}
    normalized: dict[str, dict[str, Any]] = {}
    favorite_label: str | None = None

    for label, raw_entry in source.items():
        if not isinstance(label, str):
            continue
        entry = _normalize_host_entry(raw_entry)
        # Fail-closed: only a fully valid managed entry may retain its marker.
        if label == LOCAL_AI_HOST_LABEL:
            if _is_valid_managed_local_ai_entry(entry):
                pass
            else:
                entry.pop("kind", None)
        is_managed_local_ai = _is_valid_managed_local_ai_entry(entry)
        if is_managed_local_ai:
            entry.pop("is_favorite", None)
        normalized[label] = entry
        if not is_managed_local_ai and entry.get("is_favorite") is True and favorite_label is None:
            favorite_label = label

    for label, entry in normalized.items():
        if label != favorite_label:
            entry.pop("is_favorite", None)

    managed_labels = [
        label for label, entry in normalized.items() if entry.get("kind") == LOCAL_AI_HOST_KIND
    ]
    if len(managed_labels) > 1:
        # Keep the canonical label when present, otherwise keep the first
        # managed entry.  Demote duplicate managed entries rather than
        # deleting custom hosts that happen to carry the marker.
        managed_label = (
            LOCAL_AI_HOST_LABEL if LOCAL_AI_HOST_LABEL in managed_labels else managed_labels[0]
        )
        for label in managed_labels:
            if label != managed_label:
                normalized[label].pop("kind", None)
    elif not managed_labels:
        if LOCAL_AI_HOST_LABEL not in normalized:
            normalized[LOCAL_AI_HOST_LABEL] = _local_ai_host()

    return normalized


def _user_settings_path() -> Path:
    """Return the path to the persisted user settings file."""
    return settings_path()


class SettingsFileError(RuntimeError):
    """Persistent settings are unreadable and must be recovered explicitly."""


def _load_user_settings(path: Path | None = None) -> dict:
    """Load persisted user settings when the file exists."""
    target = path or _user_settings_path()
    if target.exists():
        try:
            with target.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            backup = target.with_suffix(target.suffix + ".backup")
            if backup.is_file():
                try:
                    with backup.open("r", encoding="utf-8") as f:
                        recovered = json.load(f)
                    if isinstance(recovered, dict):
                        return recovered
                except (OSError, UnicodeError, json.JSONDecodeError):
                    pass
            raise SettingsFileError(
                "AQA settings are unreadable. The original file was preserved; "
                "restore or remove it before restarting."
            ) from error
    return {}


class Settings(BaseSettings):
    """Central application configuration."""

    # ``LLMHostConfig`` documents the stable host contract and preserves
    # unrecognized provider fields.
    known_llm_hosts: dict[str, LLMHostConfig] = Field(
        default_factory=lambda: {LOCAL_AI_HOST_LABEL: _local_ai_host()},
        # Local AI and external-host preferences are intentionally independent.
        # User supplied mappings still run through external-favorite normalization.
        validate_default=False,
    )

    # Non-secret interface preferences are persisted with the host catalogue
    # so a native desktop relaunch can restore them even though its loopback
    # web origin uses a fresh port.
    ui_locale: Literal["de", "en"] = "en"
    appearance: Literal["system", "light", "dark"] = "system"
    ai_source: Literal["integrated", "external"] = "integrated"
    local_ai_context_tokens: int = Field(
        default=DEFAULT_LOCAL_AI_CONTEXT_TOKENS, ge=8_192, le=262_144
    )
    local_ai_mtp_enabled: bool = False
    notifications_enabled: bool = True
    notification_permission_auto_attempted: bool = False
    prevent_sleep_while_generating: bool = True
    last_active_discussion_id: str | None = Field(
        default=None,
        pattern=r"^[^\\/\s]+$",
    )

    llm_timeout: int = Field(default=int(os.getenv("LLM_TIMEOUT", "120")))
    llm_connect_timeout: int = Field(default=int(os.getenv("LLM_CONNECT_TIMEOUT", "10")))
    llm_health_timeout: int = Field(default=int(os.getenv("LLM_HEALTH_TIMEOUT", "5")))
    llm_health_retries: int = Field(default=int(os.getenv("LLM_HEALTH_RETRIES", "0")))
    llm_max_retries: int = Field(default=int(os.getenv("LLM_MAX_RETRIES", "3")))
    llm_retry_delay: float = Field(default=float(os.getenv("LLM_RETRY_DELAY", "2.0")))
    prompt_library_path: str = Field(default_factory=lambda: str(prompt_library_dir()))
    prompt_defaults_path: str = Field(default_factory=lambda: str(prompt_defaults_dir()))

    api_host: str = Field(default=os.getenv("API_HOST", "127.0.0.1"))
    api_port: int = Field(default=int(os.getenv("API_PORT", "8000")))

    # Runtime environment variables remain supported; local `.env` files are
    # deliberately not read by the application configuration layer.
    model_config = ConfigDict(env_file=None)

    @model_validator(mode="after")
    def _enforce_packaged_prompt_roots(self) -> "Settings":
        """Keep BaseSettings environment aliases inside the packaged app."""

        if os.environ.get("AQA_PACKAGED_MODE") == "1":
            self.prompt_library_path = str(prompt_library_dir())
            self.prompt_defaults_path = str(prompt_defaults_dir())
        return self

    @field_validator("known_llm_hosts", mode="before")
    @classmethod
    def _normalize_known_hosts(cls, value: Any) -> dict[str, dict[str, Any]]:
        """Normalize direct construction as well as values loaded from JSON."""
        return normalize_known_llm_hosts(value)

    def _settings_file(self) -> Path:
        return _user_settings_path()

    def save_user_settings(self) -> None:
        """Persist the configured hosts atomically."""
        with mutable_data_lock:
            self.known_llm_hosts = normalize_known_llm_hosts(self.known_llm_hosts)
            payload = {
                "known_llm_hosts": dict(self.known_llm_hosts),
                "ui_locale": self.ui_locale,
                "appearance": self.appearance,
                "ai_source": self.ai_source,
                "local_ai_context_tokens": self.local_ai_context_tokens,
                "local_ai_mtp_enabled": self.local_ai_mtp_enabled,
                "notifications_enabled": self.notifications_enabled,
                "notification_permission_auto_attempted": self.notification_permission_auto_attempted,
                "prevent_sleep_while_generating": self.prevent_sleep_while_generating,
                "last_active_discussion_id": self.last_active_discussion_id,
            }
            path = self._settings_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                shutil.copyfile(path, path.with_suffix(path.suffix + ".backup"))
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary_path, path)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise

    @classmethod
    def load(cls) -> "Settings":
        """Load settings and persisted LLM host configuration."""
        user_values = _load_user_settings()

        # Use defaults when no persisted host configuration exists.
        defaults = cls._default_known_hosts()
        stored_hosts = user_values.get("known_llm_hosts")
        known = normalize_known_llm_hosts(stored_hosts or defaults)

        ui_locale = user_values.get("ui_locale")
        appearance = user_values.get("appearance")
        ai_source = user_values.get("ai_source")
        local_ai_context_tokens = user_values.get("local_ai_context_tokens")
        if (
            not isinstance(local_ai_context_tokens, int)
            or isinstance(local_ai_context_tokens, bool)
            or not 8_192 <= local_ai_context_tokens <= 262_144
        ):
            local_ai_context_tokens = DEFAULT_LOCAL_AI_CONTEXT_TOKENS
        local_ai_mtp_enabled = user_values.get("local_ai_mtp_enabled")
        notifications_enabled = user_values.get("notifications_enabled")
        notification_permission_auto_attempted = user_values.get(
            "notification_permission_auto_attempted"
        )
        prevent_sleep_while_generating = user_values.get("prevent_sleep_while_generating")
        last_active_discussion_id = user_values.get("last_active_discussion_id")
        if (
            not isinstance(last_active_discussion_id, str)
            or not last_active_discussion_id
            or any(character.isspace() for character in last_active_discussion_id)
            or "/" in last_active_discussion_id
            or "\\" in last_active_discussion_id
        ):
            last_active_discussion_id = None
        return cls(
            known_llm_hosts=known,
            ui_locale=ui_locale if ui_locale in {"de", "en"} else "en",
            appearance=appearance if appearance in ("system", "light", "dark") else "system",
            ai_source=ai_source if ai_source in {"integrated", "external"} else "integrated",
            local_ai_context_tokens=local_ai_context_tokens,
            local_ai_mtp_enabled=(
                local_ai_mtp_enabled if isinstance(local_ai_mtp_enabled, bool) else False
            ),
            notifications_enabled=(
                notifications_enabled if isinstance(notifications_enabled, bool) else True
            ),
            notification_permission_auto_attempted=(
                notification_permission_auto_attempted
                if isinstance(notification_permission_auto_attempted, bool)
                else False
            ),
            prevent_sleep_while_generating=(
                prevent_sleep_while_generating
                if isinstance(prevent_sleep_while_generating, bool)
                else True
            ),
            last_active_discussion_id=last_active_discussion_id,
        )

    @staticmethod
    def _default_known_hosts() -> dict[str, dict[str, Any]]:
        """Return exactly one managed, loopback-only Local AI host."""
        return {LOCAL_AI_HOST_LABEL: _local_ai_host()}
