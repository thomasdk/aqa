"""FastAPI transport layer for the shared application context.

Endpoints validate HTTP payloads and delegate application behavior to the
shared context. Business rules remain in the services that own them.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.config.settings import (
    LOCAL_AI_HOST_KIND,
    LOCAL_AI_HOST_LABEL,
    LOCAL_AI_HOST_URL,
    LOCAL_AI_MODEL_ALIASES,
    _is_managed_local_ai_url,
    _is_valid_managed_local_ai_entry,
    _local_ai_host,
)
from src.local_ai.catalog import BINARY_SPECS, DEFAULT_MTP_DRAFT_TOKENS, MODELS
from src.local_ai.folder_picker import (
    FolderPickerCancelled,
    FolderPickerUnavailable,
    choose_directory,
)
from src.local_ai.manager import (
    DEFAULT_CONTEXT_TOKENS,
    MIN_CONTEXT_TOKENS,
    LocalAIManager,
    LocalAIStateError,
    LocalAIStatus,
)
from src.local_ai.platform import (
    detect_hardware_profile,
    inference_memory_for_binary,
    select_binary,
)
from src.service.api_schemas import (
    DetectedModelImportJobResponse,
    ImportStartResponse,
    JobResponse,
    LocalAIDiagnosticsResponse,
    LocalAIRuntimeSelectionRecord,
    LocalAIStatusResponse,
    RevealLocalAIModelsDirectoryResponse,
)

from .dependencies import ContextDependency

router = APIRouter()

LocalAIModelId = Literal["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"]
LocalAIMtpDraftTokens = Literal[1, 2, 3, 4, 5, 6]


class _LocalAIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalAIInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: LocalAIModelId
    start_after_install: bool = False


class LocalAIDeleteModelRequest(_LocalAIRequest):
    model_id: LocalAIModelId


class LocalAIPreferredModelRequest(_LocalAIRequest):
    model_id: LocalAIModelId


class LocalAIInstallOptions(_LocalAIRequest):
    start_after_install: bool = False


class LocalAICancelRequest(_LocalAIRequest):
    job_id: str = Field(..., min_length=1)


class LocalAIImportFinalizeRequest(_LocalAIRequest):
    import_id: str = Field(..., min_length=16, max_length=64, pattern=r"^[0-9a-f]+$")


class LocalAIBackgroundImportRequest(_LocalAIRequest):
    """Optional explicit source directory for the manual-path option."""

    source_path: str | None = Field(default=None, min_length=1, max_length=4096)


class LocalAIStartRequest(_LocalAIRequest):
    model_id: LocalAIModelId
    context_tokens: int = Field(
        default=DEFAULT_CONTEXT_TOKENS,
        ge=MIN_CONTEXT_TOKENS,
        le=262_144,
    )
    mtp_enabled: bool = False
    mtp_draft_tokens: LocalAIMtpDraftTokens | None = None

    @model_validator(mode="after")
    def _reject_unused_mtp_tuning(self) -> LocalAIStartRequest:
        if not self.mtp_enabled and "mtp_draft_tokens" in self.model_fields_set:
            raise ValueError("mtp_draft_tokens requires mtp_enabled=true")
        return self


def _get_local_ai_manager(request: Request, context: ContextDependency) -> LocalAIManager:
    manager = getattr(request.app.state, "local_ai_manager", None)
    if manager is None:
        # The management screen requests status and diagnostics concurrently.
        # Construct exactly one app-owned manager so those requests
        # cannot race through manifest recovery with different lifecycle locks.
        with request.app.state.local_ai_manager_lock:
            manager = getattr(request.app.state, "local_ai_manager", None)
            if manager is None:
                manager = LocalAIManager()
                request.app.state.local_ai_manager = manager
    manager.set_install_completion_callback(
        lambda model_id: _prefer_completed_local_ai_model(model_id, context, manager)
    )
    manager.set_auto_start_completion_callback(
        lambda status: _register_started_local_ai_host(context, status)
    )
    set_callbacks = getattr(context.llm_manager, "set_managed_local_ai_request_callbacks", None)
    if callable(set_callbacks):
        set_callbacks(manager.mark_request_active, manager.mark_request_idle)
    return manager


LocalAIManagerDependency = Annotated[LocalAIManager, Depends(_get_local_ai_manager)]


def _prefer_completed_local_ai_model(model_id: str, context: Any, manager: LocalAIManager) -> None:
    """Use the first installed model without replacing a deliberate preference later."""
    if model_id not in MODELS:
        return
    if any(
        item.get("installed") is True and item.get("model_id") != model_id
        for item in manager.inventory()
        if isinstance(item, Mapping)
    ):
        return
    entry = context.settings.known_llm_hosts.get(LOCAL_AI_HOST_LABEL)
    if not isinstance(entry, dict) or not _is_valid_managed_local_ai_entry(entry):
        return
    entry.pop("is_favorite", None)
    aliases_by_id = dict(zip(MODELS, LOCAL_AI_MODEL_ALIASES, strict=True))
    preferred_alias = aliases_by_id[model_id]
    if entry.get("model") == preferred_alias:
        context.settings.save_user_settings()
        return
    entry["model"] = preferred_alias
    entry["models"] = [
        preferred_alias,
        *(alias for alias in LOCAL_AI_MODEL_ALIASES if alias != preferred_alias),
    ]
    context.settings.save_user_settings()


def _register_started_local_ai_host(context: Any, status: LocalAIStatus) -> None:
    """Publish the actual endpoint selected by an install-time automatic start."""
    _register_local_ai_host(context, status)
    invalidate = getattr(context.llm_manager, "invalidate_model_list", None)
    if callable(invalidate):
        invalidate(status.host)


_LOCAL_AI_STATES = frozenset(
    {
        "not_installed",
        "downloading",
        "importing",
        "installed",
        "starting",
        "running",
        "sleeping",
        "error",
        "stopped",
        "cancelling",
        "cancelled",
    }
)
_ACCELERATOR_LABELS = {
    "cpu": "CPU",
    "metal": "Metal",
    "cuda": "CUDA",
    "hip": "HIP",
    "rocm": "ROCm",
    "sycl": "SYCL",
    "opencl": "OpenCL",
    "gpu": "GPU",
}


def _safe_text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, str) or any(token in value for token in ("/", "\\", "--", "http:")):
        return None
    return " ".join(value.split())[:limit] or None


def _safe_nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _status_identity(raw: Mapping[str, Any]) -> dict[str, Any]:
    state = str(raw.get("state") or "error")
    state = state if state in _LOCAL_AI_STATES else "error"
    model_id = raw.get("model_id") if raw.get("model_id") in MODELS else None
    model_name = _safe_text(raw.get("model_name"), limit=200)
    if model_name is None:
        model_name = MODELS[model_id].label if model_id else None
    host_raw = raw.get("host")
    host = (
        host_raw
        if isinstance(host_raw, str)
        and host_raw.startswith("http://127.0.0.1:")
        and "/" not in host_raw[len("http://127.0.0.1:") :]
        else None
    )
    port = _safe_nonnegative_int(raw.get("port"))
    port = port if port is not None and 1 <= port <= 65535 and host is not None else None
    return {
        "state": state,
        "model_id": model_id,
        "model_name": model_name,
        "host": host,
        "port": port,
        "host_ready": state in {"running", "sleeping"} and host is not None,
        "integrity": "verified"
        if state in {"installed", "running", "sleeping", "stopped"}
        else "unknown",
        "accelerator_label": _ACCELERATOR_LABELS.get(raw.get("accelerator")),
        "error_code": _safe_text(raw.get("error_code"), limit=64),
        "message": _safe_text(raw.get("message"), limit=240) or "",
    }


def _status_hardware(hardware: Any, runtime_binary: Any) -> tuple[Any, dict[str, Any]]:
    if hardware is None:
        try:
            hardware = detect_hardware_profile()
        except (OSError, TypeError, ValueError):
            hardware = None
    os_label = _safe_text(getattr(hardware, "os_label", None), limit=100)
    cpu_label = _safe_text(getattr(hardware, "cpu_label", None), limit=120)
    gpu_label = _safe_text(getattr(hardware, "gpu_label", None), limit=120)
    logical_cpu_count = _safe_nonnegative_int(getattr(hardware, "logical_cpu_count", None))
    ram_gb = _safe_nonnegative_int(getattr(hardware, "ram_gb", None))
    inference_memory_gb = None
    inference_memory_kind = None
    if hardware is not None:
        try:
            binary = runtime_binary if runtime_binary is not None else select_binary(hardware)
            inference_memory = inference_memory_for_binary(hardware, binary)
            inference_memory_gb = _safe_nonnegative_int(inference_memory.gb)
            inference_memory_kind = inference_memory.kind
        except (OSError, TypeError, ValueError):
            pass
    if inference_memory_gb is None or inference_memory_kind not in {"ram", "vram", "unified"}:
        inference_memory_gb = None
        inference_memory_kind = None
    return hardware, {
        "os_label": os_label,
        "cpu_label": cpu_label,
        "gpu_label": gpu_label,
        "logical_cpu_count": logical_cpu_count
        if logical_cpu_count and logical_cpu_count > 0
        else None,
        "ram_gb": ram_gb if ram_gb and ram_gb > 0 else None,
        "inference_memory_gb": inference_memory_gb,
        "inference_memory_kind": inference_memory_kind,
    }


def _status_payload(
    status: LocalAIStatus, *, hardware: Any = None, runtime_binary: Any = None
) -> dict[str, Any]:
    raw = status.to_dict() if hasattr(status, "to_dict") else dict(status)
    _, hardware_payload = _status_hardware(hardware, runtime_binary)
    return {
        **_status_identity(raw),
        "download_bytes": max(0, int(raw.get("downloaded_bytes") or 0)),
        "download_total": max(0, int(raw.get("total_bytes") or 0)),
        "available_disk_bytes": _safe_nonnegative_int(raw.get("available_disk_bytes")),
        "download_phase": raw.get("download_phase")
        if raw.get("download_phase")
        in {"preparing", "runtime", "main_model", "mtp_drafter", "finalizing"}
        else None,
        "import_bytes": max(0, int(raw.get("import_bytes") or 0)),
        "import_total": max(0, int(raw.get("import_total") or 0)),
        "import_phase": raw.get("import_phase")
        if raw.get("import_phase") in {"copying", "verifying"}
        else None,
        "context_tokens": raw.get("context_tokens"),
        "mtp_enabled": bool(raw.get("mtp_enabled", False)),
        "mtp_draft_tokens": raw.get("mtp_draft_tokens"),
        "job_id": raw.get("job_id") if isinstance(raw.get("job_id"), str) else None,
        "operation_kind": raw.get("operation_kind")
        if raw.get("operation_kind") in {"model_download", "model_import", "runtime_update"}
        else None,
        "operation_state": raw.get("operation_state")
        if raw.get("operation_state") in {"downloading", "importing", "cancelling", "error"}
        else None,
        "operation_model_id": raw.get("operation_model_id")
        if raw.get("operation_model_id") in MODELS
        else None,
        **hardware_payload,
    }


def _managed_local_ai_preferred_model_id(hosts: Mapping[str, Any]) -> str | None:
    entry = hosts.get(LOCAL_AI_HOST_LABEL)
    if not isinstance(entry, Mapping) or not _is_valid_managed_local_ai_entry(entry):
        return None
    aliases_to_ids = dict(zip(LOCAL_AI_MODEL_ALIASES, MODELS, strict=True))
    return aliases_to_ids.get(entry.get("model"))


# Allow-list of accelerator labels the UI is allowed to render.  Anything
# outside this set is mapped to "CPU" so the user never sees a probe label
# such as "vulkan" lowercase or a future internal slug.  Order is fixed.
_RUNTIME_ACCELERATOR_LABELS: Mapping[str, str] = {
    "cpu": "CPU",
    "metal": "Metal",
    "cuda": "CUDA",
    "rocm": "ROCm",
    "hip": "HIP",
    "vulkan": "Vulkan",
    "sycl": "SYCL",
    "opencl": "OpenCL",
}

# Safe, browser-facing decision bases.  These are the only values the UI
# will ever see, regardless of how the binary was chosen.
_DECISION_BASIS_COMPATIBLE = "detected compatible runtime"
_DECISION_BASIS_CPU_FALLBACK = "safe CPU fallback"


def _sanitize_runtime_rationale(
    binary: Any,
    *,
    installed_binary: Any = None,
    capability_state: str = "unknown",
) -> dict[str, Any]:
    """Return the typed, browser-safe rationale for the selected binary.

    The rationale contains *only*:

    * ``runtime_profile`` — the catalog profile key (e.g. ``macos-arm64-metal``).
      This is a fixed label, never a path or URL.
    * ``accelerator_label`` — a small allow-listed label (``Metal``/``CUDA``/
      ``ROCm``/``HIP``/``Vulkan``/``CPU``) or ``None`` if the value cannot
      be normalised.
    * ``engine_name`` — the generic executable name (``llama-server`` or
      ``llama-server.exe``).  No directory, no URL.
    * ``decision_basis`` — one of the two short strings above.
    * ``runtime_installed`` — whether the manager currently has a verified
      binary on disk.
    * ``acceleration_confirmed`` — whether an actual managed runtime start
      verified GPU offload.

    Paths, full command lines, driver output, and raw probe text are
    intentionally absent.  When the manager already owns a verified
    installed binary, that binary's facts are used in preference to the
    candidate selected for a future install.
    """
    chosen = installed_binary if installed_binary is not None else binary
    profile = getattr(chosen, "profile", None) or getattr(binary, "profile", None)
    accelerator = getattr(chosen, "accelerator", None) or getattr(binary, "accelerator", None)
    engine = getattr(chosen, "engine_name", None)
    is_cpu = accelerator == "cpu" or accelerator is None
    cpu_confirmed = is_cpu and capability_state == "cpu_confirmed"
    cpu_selected = is_cpu and installed_binary is not None
    return {
        "runtime_profile": str(profile) if profile else None,
        "accelerator_label": (
            _RUNTIME_ACCELERATOR_LABELS.get(str(accelerator).lower())
            if not is_cpu or cpu_confirmed or cpu_selected
            else None
        ),
        "engine_name": engine if engine in {"llama-server", "llama-server.exe"} else None,
        "decision_basis": (
            _DECISION_BASIS_CPU_FALLBACK
            if cpu_confirmed
            else _DECISION_BASIS_COMPATIBLE
            if not is_cpu
            else None
        ),
        "acceleration_confirmed": capability_state == "gpu_verified",
    }


def _resolved_runtime_selection(
    manager: LocalAIManager,
    hardware: Any = None,
    *,
    capability_state: str = "unknown",
) -> tuple[dict[str, Any], Any]:
    """Build the sanitized selection rationale for the API surface.

    The selection is performed exactly once per call.  When the manager
    has a verified installed binary (e.g. restored from the on-disk
    manifest), that binary's profile/accelerator/engine is preferred so
    the UI can describe *what is installed* and not merely what would
    be selected for a fresh install.  The candidate is always computed
    as a fallback so stopped/uninstalled states still expose a clear
    answer.
    """
    profile = hardware if hardware is not None else detect_hardware_profile()
    candidate = select_binary(profile)
    installed: Any = None
    installed_spec = getattr(manager, "_binary_spec", None)
    installed_path = getattr(manager, "_binary_path", None)
    has_installed_path = bool(installed_path) and isinstance(
        installed_path, (str, bytes, os.PathLike)
    )
    installed_profile = (
        getattr(installed_spec, "profile", None) if installed_spec is not None else None
    )
    installed_engine = (
        getattr(installed_spec, "engine_name", None) if installed_spec is not None else None
    )
    if (
        has_installed_path
        and isinstance(installed_profile, str)
        and installed_engine in {"llama-server", "llama-server.exe"}
    ):
        installed = installed_spec
    chosen = installed if installed is not None else candidate
    rationale = _sanitize_runtime_rationale(
        candidate,
        installed_binary=installed,
        capability_state=capability_state,
    )
    rationale["runtime_installed"] = has_installed_path
    return rationale, chosen


def _sanitized_model_inventory(manager: LocalAIManager) -> list[dict[str, Any]]:
    """Return only safe model inventory facts for the browser.

    ``LocalAIManager.inventory()`` needs absolute artifact paths for local
    lifecycle work, but a browser-facing status response must never disclose
    them.  Project the manager output through this allow-list rather than
    deleting known keys, so future manager additions are private by default.
    """
    safe_inventory: list[dict[str, Any]] = []
    for raw in manager.inventory():
        if not isinstance(raw, Mapping):
            continue
        model_id = raw.get("model_id")
        if model_id not in MODELS:
            continue
        entry: dict[str, Any] = {
            "model_id": model_id,
            "api_alias": MODELS[model_id].api_alias,
            "installed": bool(raw.get("installed", False)),
            "integrity": raw.get("integrity")
            if raw.get("integrity") in {"unknown", "verified", "failed"}
            else "unknown",
        }
        # Basenames are catalog metadata, not local paths. The browser uses
        # them to recognise supported portable-bundle layouts without guessing
        # from arbitrary paths.
        spec = MODELS[model_id]
        entry["import_files"] = {
            "main": spec.model_filename,
            "draft": spec.draft_filename,
        }
        for key in ("model_bytes", "draft_bytes"):
            value = raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                entry[key] = value
        safe_inventory.append(entry)
    return safe_inventory


def _status_with_inventory(
    manager: LocalAIManager, preferred_model_id: str | None = None
) -> dict[str, Any]:
    capability_state = "unknown"
    try:
        hardware = detect_hardware_profile()
        capability_state = manager.runtime_capability_state()
        if capability_state in {"cpu_confirmed", "gpu_verified"}:
            hardware = replace(hardware, capability_state=capability_state)
    except (OSError, TypeError, ValueError):
        hardware = None
    runtime_selection: dict[str, Any] | None = None
    runtime_binary: Any = None
    if hardware is not None:
        try:
            runtime_selection, runtime_binary = _resolved_runtime_selection(
                manager, hardware, capability_state=capability_state
            )
        except (OSError, TypeError, ValueError):
            runtime_selection = None
    payload = _status_payload(manager.status(), hardware=hardware, runtime_binary=runtime_binary)
    payload["models"] = _sanitized_model_inventory(manager)
    payload["preferred_model_id"] = preferred_model_id
    payload["runtime_selection"] = runtime_selection or {
        "runtime_profile": None,
        "accelerator_label": None,
        "engine_name": None,
        "decision_basis": None,
        "runtime_installed": False,
        "acceleration_confirmed": False,
    }
    payload["runtime_installed"] = bool(
        getattr(manager, "_binary_path", None)
        or payload["runtime_selection"].get("runtime_installed")
    )
    return payload


def _local_ai_error(exc: Exception, fallback: str) -> HTTPException:
    detail = " ".join(str(exc).split())
    if not detail or any(token in detail for token in ("/", "\\", "--", "http:")):
        detail = fallback
    code = getattr(exc, "code", None) if isinstance(exc, LocalAIStateError) else None
    if not isinstance(code, str) or not re.fullmatch(r"[a-z_]{3,64}", code):
        code = "invalid_request" if isinstance(exc, ValueError) else "local_ai_unavailable"
    status = 409 if code in {"busy", "state_conflict"} else 422
    if code in {
        "process_exited",
        "startup_timeout",
        "startup_failed",
        "runtime_incompatible",
        "accelerator_failed",
    }:
        status = 503
    if code in {
        "port_conflict",
        "permission_denied",
        "insufficient_resources",
        "insufficient_disk_space",
        "artifact_invalid",
    }:
        status = 422
    error = HTTPException(status_code=status, detail=detail[:240])
    error.error_code = code
    return error


def _open_models_directory(manager: LocalAIManager) -> None:
    """Open the managed models directory without exposing its path to the browser."""

    try:
        directory = (Path(manager.local_dir) / "models").resolve()
    except (OSError, RuntimeError, TypeError, AttributeError):
        raise HTTPException(status_code=404, detail="Models directory is unavailable") from None
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="Models directory is unavailable")

    if sys.platform == "darwin":
        argv = ["open", str(directory)]
    elif sys.platform == "win32":
        argv = ["explorer", str(directory)]
    else:
        argv = ["xdg-open", str(directory)]
    try:
        result = subprocess.run(
            argv,
            check=False,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if isinstance(result.returncode, int) and result.returncode != 0:
            raise HTTPException(status_code=502, detail="Models directory is unavailable")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HTTPException(status_code=502, detail="Models directory is unavailable") from error


@router.get("/api/local-ai/status", response_model=LocalAIStatusResponse)
def get_local_ai_status(
    context: ContextDependency, manager: LocalAIManagerDependency
) -> dict[str, Any]:
    return _status_with_inventory(
        manager,
        _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts),
    )


@router.post(
    "/api/local-ai/models/reveal-directory",
    response_model=RevealLocalAIModelsDirectoryResponse,
)
def reveal_local_ai_models_directory(
    manager: LocalAIManagerDependency,
) -> RevealLocalAIModelsDirectoryResponse:
    """Open the managed local AI models directory without returning its path."""

    _open_models_directory(manager)
    return RevealLocalAIModelsDirectoryResponse(status="ok")


@router.get("/api/local-ai/diagnostics", response_model=LocalAIDiagnosticsResponse)
def get_local_ai_diagnostics(
    context: ContextDependency, manager: LocalAIManagerDependency
) -> dict[str, Any]:
    """Return a bounded diagnostic record with managed file paths redacted."""
    details = manager.runtime_details()
    status = manager.status()
    preferred_model_id = _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    command_reference = (
        LocalAIManager.safe_command_reference(
            manager.configured_command_reference(
                preferred_model_id,
                context_tokens=context.settings.local_ai_context_tokens,
                mtp_enabled=context.settings.local_ai_mtp_enabled,
            )
        )
        if preferred_model_id is not None
        else None
    )
    command_kind = (
        "active"
        if command_reference is not None and status.state in {"running", "sleeping"}
        else "next_start"
        if command_reference is not None
        else None
    )
    if command_reference is None and status.state == "error":
        command_reference = LocalAIManager.safe_command_reference(details.get("command_reference"))
        if command_reference is not None:
            command_kind = "last_attempt"
    try:
        stored = manager.read_runtime_selection_record()
        if stored is None:
            selection_diagnostics = {"state": "missing"}
        else:
            record = LocalAIRuntimeSelectionRecord.model_validate_json(stored)
            profiles = [entry.profile for entry in record.attempts]
            if record.selected_profile is not None:
                profiles.append(record.selected_profile)
            if any(profile not in BINARY_SPECS for profile in profiles):
                raise ValueError("unknown runtime profile")
            if (record.outcome == "selected") != (record.selected_profile is not None):
                raise ValueError("inconsistent selection outcome")
            selection_diagnostics = {
                "state": "available",
                "record": record.model_dump(exclude_none=True),
            }
    except (OSError, ValueError, ValidationError):
        selection_diagnostics = {"state": "invalid"}
    return {
        "command_reference": command_reference,
        "command_kind": command_kind,
        "error_code": _safe_text(details.get("error_code"), limit=64),
        "exit_code": details.get("exit_code")
        if isinstance(details.get("exit_code"), int)
        and not isinstance(details.get("exit_code"), bool)
        else None,
        "log_tail": [
            item
            for item in details.get("log_tail", [])
            if isinstance(item, str) and _safe_text(item, limit=240) == item
        ][:12],
        "runtime_selection_diagnostics": selection_diagnostics,
    }


@router.put("/api/local-ai/preferred-model", response_model=LocalAIStatusResponse)
def set_local_ai_preferred_model(
    payload: LocalAIPreferredModelRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, Any]:
    """Persist the model used by the managed Integrated AI host on its next start."""
    entry = context.settings.known_llm_hosts.get(LOCAL_AI_HOST_LABEL)
    if not isinstance(entry, dict) or not _is_valid_managed_local_ai_entry(entry):
        raise HTTPException(status_code=409, detail="Managed Integrated AI host is unavailable")

    # Preference is meaningful only for a verified local model the user can
    # actually start.  The UI mirrors this rule, but it belongs here as an
    # invariant too: browser state can be stale and callers may use the API
    # directly.
    installed_ids = {
        item.get("model_id")
        for item in manager.inventory()
        if isinstance(item, Mapping) and item.get("installed") is True
    }
    if payload.model_id not in installed_ids:
        raise HTTPException(status_code=409, detail="Install the model before making it preferred")

    aliases_by_id = dict(zip(MODELS, LOCAL_AI_MODEL_ALIASES, strict=True))
    preferred_alias = aliases_by_id[payload.model_id]
    entry.pop("is_favorite", None)
    entry["model"] = preferred_alias
    entry["models"] = [
        preferred_alias,
        *(alias for alias in LOCAL_AI_MODEL_ALIASES if alias != preferred_alias),
    ]
    context.settings.save_user_settings()
    return _status_with_inventory(manager, payload.model_id)


@router.post("/api/local-ai/models/{model_id}/install", response_model=JobResponse)
def install_local_ai_model(
    model_id: LocalAIModelId,
    payload: LocalAIInstallOptions,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, str]:
    try:
        job_id = manager.install(
            model_id,
            start_after_install=payload.start_after_install,
            context_tokens=context.settings.local_ai_context_tokens,
            mtp_enabled=context.settings.local_ai_mtp_enabled,
            mtp_draft_tokens=DEFAULT_MTP_DRAFT_TOKENS,
        )
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI installation could not be started") from exc
    return {"job_id": job_id}


@router.post("/api/local-ai/models/{model_id}/import", response_model=ImportStartResponse)
def begin_local_ai_model_import(
    model_id: LocalAIModelId, manager: LocalAIManagerDependency
) -> dict[str, str]:
    """Create a private staging area for a browser-selected portable bundle."""
    try:
        session = manager.begin_import(model_id)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Model import could not be started") from exc
    return {"import_id": session.import_id}


def _require_packaged_loopback(request: Request) -> None:
    """Restrict native dialogs and arbitrary source paths to the packaged app."""
    if os.environ.get("AQA_PACKAGED_MODE") != "1":
        raise HTTPException(status_code=404, detail="Packaged model import is unavailable")
    host = request.client.host if request.client else ""
    # ``testclient`` is Starlette's in-process test transport, not a network
    # hostname.  Keeping it here lets API tests exercise the same gate.
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=403, detail="Packaged model import requires a local connection"
        )


@router.post(
    "/api/local-ai/models/import-from-directory",
    response_model=DetectedModelImportJobResponse,
)
def import_local_ai_model_from_directory(
    payload: LocalAIBackgroundImportRequest,
    request: Request,
    manager: LocalAIManagerDependency,
) -> dict[str, str]:
    """Detect and copy one exact catalog model from a selected portable bundle."""
    _require_packaged_loopback(request)
    source_path = payload.source_path
    if source_path is None:
        try:
            source_path = str(choose_directory())
        except FolderPickerUnavailable as exc:
            raise HTTPException(
                status_code=501, detail="No native directory picker is available"
            ) from exc
        except FolderPickerCancelled as exc:
            raise HTTPException(
                status_code=409, detail="Directory selection was cancelled"
            ) from exc
    try:
        job_id, model_id = manager.start_detected_background_import(source_path)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Model import could not be started") from exc
    return {"job_id": job_id, "model_id": model_id}


@router.put("/api/local-ai/imports/{import_id}/{artifact}")
async def upload_local_ai_import_part(
    import_id: str,
    artifact: Literal["main", "draft"],
    request: Request,
    manager: LocalAIManagerDependency,
) -> dict[str, str]:
    """Stream one selected artifact without multipart buffering in memory."""
    if not re.fullmatch(r"[0-9a-f]{16,64}", import_id):
        raise HTTPException(status_code=422, detail="Invalid model import")
    try:
        destination = manager.import_part_path(import_id, artifact)
        destination.unlink(missing_ok=True)
        written = 0
        with destination.open("xb") as stream:
            async for chunk in request.stream():
                if not chunk:
                    continue
                written += len(chunk)
                # A selected Gemma artifact is several GB, but an unbounded
                # localhost request must never fill a disk accidentally.
                if written > 32 * 1024 * 1024 * 1024:
                    raise LocalAIStateError("model import is too large")
                stream.write(chunk)
        if written < 8:
            raise LocalAIStateError("model import is incomplete")
    except (LocalAIStateError, OSError, ValueError) as exc:
        try:
            destination.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise _local_ai_error(exc, "Model import failed") from exc
    return {"status": "uploaded"}


@router.post("/api/local-ai/imports/finalize", response_model=LocalAIStatusResponse)
def finalize_local_ai_model_import(
    payload: LocalAIImportFinalizeRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, Any]:
    try:
        manager.finish_import(payload.import_id)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Model import could not be completed") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


@router.delete("/api/local-ai/imports/{import_id}")
def abort_local_ai_model_import(
    import_id: str, manager: LocalAIManagerDependency
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{16,64}", import_id):
        raise HTTPException(status_code=422, detail="Invalid model import")
    try:
        manager.cancel_import(import_id)
    except LocalAIStateError:
        manager.abort_import(import_id)
    return {"status": "cancelled"}


@router.post("/api/local-ai/install", response_model=JobResponse)
def install_local_ai(
    payload: LocalAIInstallRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, str]:
    try:
        job_id = manager.install(
            payload.model_id,
            start_after_install=payload.start_after_install,
            context_tokens=context.settings.local_ai_context_tokens,
            mtp_enabled=context.settings.local_ai_mtp_enabled,
            mtp_draft_tokens=DEFAULT_MTP_DRAFT_TOKENS,
        )
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI installation could not be started") from exc
    return {"job_id": job_id}


@router.post("/api/local-ai/install/cancel", response_model=LocalAIStatusResponse)
def cancel_local_ai_install(
    payload: LocalAICancelRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, Any]:
    try:
        manager.cancel_install(payload.job_id)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI installation could not be cancelled") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


@router.delete("/api/local-ai/models/{model_id}", response_model=LocalAIStatusResponse)
def delete_local_ai_model_by_id(
    model_id: LocalAIModelId,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, Any]:
    try:
        manager.delete_model(model_id)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI model could not be deleted") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


@router.post("/api/local-ai/models/delete", response_model=LocalAIStatusResponse)
def delete_local_ai_model(
    payload: LocalAIDeleteModelRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, Any]:
    try:
        manager.delete_model(payload.model_id)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI model could not be deleted") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


@router.post("/api/local-ai/runtime/update", response_model=JobResponse)
def update_local_ai_runtime(
    context: ContextDependency,
    manager: LocalAIManagerDependency,
    cpu_fallback: bool = False,
) -> dict[str, str]:
    try:
        job_id = manager.update_runtime(
            cpu_fallback=cpu_fallback,
            model_id=_managed_local_ai_preferred_model_id(context.settings.known_llm_hosts),
            context_tokens=context.settings.local_ai_context_tokens,
            mtp_enabled=context.settings.local_ai_mtp_enabled,
            mtp_draft_tokens=DEFAULT_MTP_DRAFT_TOKENS,
        )
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI runtime update could not be started") from exc
    return {"job_id": job_id}


@router.delete("/api/local-ai/runtime", response_model=LocalAIStatusResponse)
def delete_local_ai_runtime(
    context: ContextDependency, manager: LocalAIManagerDependency
) -> dict[str, Any]:
    try:
        manager.delete_runtime()
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI runtime could not be deleted") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


def _register_local_ai_host(context: Any, status: LocalAIStatus) -> None:
    payload = _status_payload(status)
    if not payload["host_ready"] or not payload["model_id"] or not payload["model_name"]:
        raise LocalAIStateError("local server did not report a usable host")
    model = MODELS.get(payload["model_id"])
    if model is None:
        raise LocalAIStateError("local server model is not in the catalog")
    if not _is_managed_local_ai_url(payload["host"]):
        raise LocalAIStateError("local server did not report a usable host")

    hosts = context.settings.known_llm_hosts

    # Fail-closed: a user-defined host using the reserved label must not be
    # silently overwritten by the managed Integrated AI host. A valid managed entry
    # may carry either supported preferred model; external-host preference remains
    # independent of the managed host.
    reserved = hosts.get(LOCAL_AI_HOST_LABEL)
    if reserved is not None and not _is_valid_managed_local_ai_entry(reserved):
        raise LocalAIStateError(
            f"A custom '{LOCAL_AI_HOST_LABEL}' host already exists; "
            "remove or rename it before using Integrated AI",
            code="state_conflict",
        )

    factory_host = _local_ai_host()
    preferred_model = reserved.get("model") if reserved is not None else factory_host["model"]

    managed_host = {
        "url": payload["host"],
        "api_key": "",
        "model": preferred_model,
        "models": [
            preferred_model,
            *(alias for alias in LOCAL_AI_MODEL_ALIASES if alias != preferred_model),
        ],
        "kind": LOCAL_AI_HOST_KIND,
    }
    if isinstance(status.context_tokens, int) and not isinstance(status.context_tokens, bool):
        if status.context_tokens > 0:
            managed_host["context_tokens"] = status.context_tokens
    hosts[LOCAL_AI_HOST_LABEL] = managed_host
    context.settings.save_user_settings()


@router.post("/api/local-ai/start", response_model=LocalAIStatusResponse)
def start_local_ai(
    payload: LocalAIStartRequest,
    context: ContextDependency,
    manager: LocalAIManagerDependency,
) -> dict[str, Any]:
    try:
        mtp_draft_tokens = (
            payload.mtp_draft_tokens
            if payload.mtp_draft_tokens is not None
            else DEFAULT_MTP_DRAFT_TOKENS
        )
        status = manager.start(
            payload.model_id,
            context_tokens=payload.context_tokens,
            mtp_enabled=payload.mtp_enabled,
            mtp_draft_tokens=mtp_draft_tokens,
        )
        if status.state in {"running", "sleeping"} and status.host and status.model_name:
            _register_local_ai_host(context, status)
            invalidate = getattr(context.llm_manager, "invalidate_model_list", None)
            if callable(invalidate):
                invalidate(status.host)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI server could not be started") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


@router.post("/api/local-ai/stop", response_model=LocalAIStatusResponse)
def stop_local_ai(context: ContextDependency, manager: LocalAIManagerDependency) -> dict[str, Any]:
    try:
        managed = context.settings.known_llm_hosts.get(LOCAL_AI_HOST_LABEL)
        managed_url = (
            managed.get("url")
            if isinstance(managed, Mapping) and _is_valid_managed_local_ai_entry(managed)
            else LOCAL_AI_HOST_URL
        )
        manager.stop()
        invalidate = getattr(context.llm_manager, "invalidate_model_list", None)
        if callable(invalidate):
            invalidate(managed_url)
    except (LocalAIStateError, ValueError) as exc:
        raise _local_ai_error(exc, "Integrated AI server could not be stopped") from exc
    return _status_with_inventory(
        manager, _managed_local_ai_preferred_model_id(context.settings.known_llm_hosts)
    )


_ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
