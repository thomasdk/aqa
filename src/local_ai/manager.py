"""Owned, loopback-only lifecycle management for the Local AI server."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests

from src.config.settings import DEFAULT_LOCAL_AI_CONTEXT_TOKENS

from .catalog import (
    BINARY_SPECS,
    DEFAULT_MTP_DRAFT_TOKENS,
    IDLE_SLEEP_SECONDS,
    LOCAL_HOST,
    MODELS,
    MTP_DRAFT_TOKEN_CHOICES,
    binary_for_profile,
    latest_binary_for_profile,  # noqa: F401 - retained as a test seam for legacy updates
)
from .jobs import (
    BackgroundImportJob as _BackgroundImportJob,
)
from .jobs import (
    ImportSession as _ImportSession,
)
from .jobs import (
    InstallJob as _InstallJob,
)
from .platform import (
    RuntimeProbe,
    binary_candidates,
    detect_hardware_profile,
    parse_runtime_devices,
    select_binary,
)
from .process_launch import hidden_console_flags
from .status import LocalAIStatus

# The managed models support up to 128k tokens, but 32k is the practical
# default for a workstation.  The value controls llama.cpp's allocated KV
# context as well as the discussion service's admission limit.
DEFAULT_CONTEXT_TOKENS = DEFAULT_LOCAL_AI_CONTEXT_TOKENS
MIN_CONTEXT_TOKENS = 8_192
STALE_PROCESS_TERM_TIMEOUT = 2.0
STALE_PROCESS_KILL_TIMEOUT = 1.0
# The first launch of a freshly extracted macOS binary can spend several
# seconds in dyld and Metal initialization before printing --help. A packaged
# M2 cold start took about 50 seconds; allow that startup while keeping the
# compatibility probe bounded.
RUNTIME_PREFLIGHT_TIMEOUT = 120.0
# Device enumeration also initializes Metal in a packaged app. Its first M2
# probe took 26.5 seconds even after the help check had succeeded.
RUNTIME_DEVICE_PROBE_TIMEOUT = 120.0
RUNTIME_OFFLOAD_LOG_GRACE_SECONDS = 0.5
_REQUIRED_RUNTIME_FLAGS = frozenset(
    {
        "--model",
        "--model-draft",
        "--spec-type",
        "--spec-draft-n-max",
        "--alias",
        "--flash-attn",
        "--ctx-size",
        "--temp",
        "--top-p",
        "--top-k",
        "--n-gpu-layers",
        "--fit",
        "--device",
        "--verbosity",
        "--sleep-idle-seconds",
        "--host",
        "--port",
    }
)

# Keep catalog download helpers at the module boundary so runtime operations can
# fail closed when an optional distribution capability is unavailable.
try:  # pragma: no cover - import availability depends on the distribution
    from .downloads import (
        binary_archive_path,
        binary_companion_archive_path,
        binary_companion_download_spec,
        binary_download_spec,
        binary_extract_path,
        bundled_third_party_license_path,
        download_catalog_artifact,
        download_verified,
        draft_download_spec,
        extract_verified_archive,
        install_verified_companion_archive,
        local_ai_dir,
        model_download_spec,
    )
except ImportError:  # pragma: no cover - unavailable distribution capability
    binary_archive_path = None
    binary_companion_archive_path = None
    binary_companion_download_spec = None
    binary_download_spec = None
    binary_extract_path = None
    bundled_third_party_license_path = None
    download_catalog_artifact = None
    download_verified = None
    extract_verified_archive = None
    install_verified_companion_archive = None
    local_ai_dir = None
    model_download_spec = None
    draft_download_spec = None


class LocalAIStateError(RuntimeError):
    """A safe lifecycle transition could not be performed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "local_ai_unavailable",
        selection_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.selection_reason = selection_reason


class LocalAIManager:
    """Own at most one verified llama-server child process."""

    def __init__(
        self,
        local_dir: Path | str | None = None,
        *,
        binary_path: Path | str | None = None,
        binary_spec: Any = None,
        model_paths: Mapping[str, Path | str] | None = None,
        draft_paths: Mapping[str, Path | str] | None = None,
        port: int = 8080,
        cpu_threads: int | None = None,
        accelerator_available: bool | None = None,
        startup_timeout: float = 120.0,
        health_interval: float = 0.05,
    ) -> None:
        if local_dir is None:
            if local_ai_dir is not None:
                local_dir = local_ai_dir()
            else:
                local_dir = Path.home() / ".local" / "share" / "aqa" / "local-ai"
        self.local_dir = Path(local_dir).expanduser().resolve()
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self._owner_marker_path = self.local_dir / "owner.json"
        self._manifest_path = self.local_dir / "manifest.json"

        self._binary_spec: Any = binary_spec
        self._binary_path = Path(binary_path).expanduser().resolve() if binary_path else None
        self._model_paths = {key: Path(value) for key, value in (model_paths or {}).items()}
        self._draft_paths = {key: Path(value) for key, value in (draft_paths or {}).items()}
        self._configured_port = self._validate_port(port)
        self._port: int | None = None
        self._cpu_threads = cpu_threads if cpu_threads is not None else (os.cpu_count() or 1)
        if (
            not isinstance(self._cpu_threads, int)
            or isinstance(self._cpu_threads, bool)
            or self._cpu_threads < 1
        ):
            raise ValueError("cpu_threads must be a positive integer")
        self._accelerator_available = accelerator_available
        self._startup_timeout = max(0.1, float(startup_timeout))
        self._health_interval = max(0.0, float(health_interval))

        self._lock = threading.RLock()
        self._process: Any = None
        self._process_command: list[str] | None = None
        self._owner_pid: int | None = None
        self._active_requests = 0
        self._last_request_idle_at: float | None = None
        self._config: tuple[Any, ...] | None = None
        self._server_model_name: str | None = None
        self._status = LocalAIStatus()
        self._operation_status: LocalAIStatus | None = None
        self._jobs: dict[str, _InstallJob] = {}
        self._imports: dict[str, _ImportSession] = {}
        self._background_import_jobs: dict[str, _BackgroundImportJob] = {}
        self._log_lines: deque[str] = deque(maxlen=200)
        self._last_diagnostic: dict[str, Any] = {}
        self._diagnostics_path = self.local_dir / "startup-diagnostics.json"
        self._selection_diagnostics_path = self.local_dir / "runtime-selection.json"
        self._selection_record: dict[str, Any] | None = None
        self._start_in_flight: tuple[Any, ...] | None = None
        self._install_completion_callback: Callable[[str], None] | None = None
        self._auto_start_completion_callback: Callable[[LocalAIStatus], None] | None = None
        self._runtime_probe = RuntimeProbe("failed")
        self._runtime_device: str | None = None
        self._runtime_offload_verified = False
        self._runtime_offloaded_layers = 0
        self._cpu_fallback_confirmed = False

        self._load_manifest()
        self._load_startup_diagnostic()

    @staticmethod
    def _validate_port(port: int) -> int:
        if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
            raise ValueError("port must be an integer from 0 through 65535")
        return port

    def _load_manifest(self) -> None:
        """Reconstruct inventory from the atomic JSON manifest and verify files."""
        if not self._manifest_path.exists():
            return
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return
        with self._lock:
            self._apply_manifest_runtime(payload.get("runtime"))
            self._apply_manifest_models(payload.get("models"))
            if self._binary_path is not None and self._model_paths:
                # A fresh manager has no active process to restore, but verified
                # runtime and model artifacts are immediately startable.
                self._status = LocalAIStatus(state="installed")

    def _apply_manifest_runtime(self, runtime: Any) -> None:
        if not isinstance(runtime, dict):
            return
        required_fields = {
            "profile",
            "platform",
            "accelerator",
            "version",
            "executable",
            "archive_path",
            "archive_filename",
            "archive_bytes",
            "archive_sha256",
            "shared_libraries",
        }
        if not required_fields.issubset(runtime) or not isinstance(
            runtime["shared_libraries"], list
        ):
            return
        profile = runtime.get("profile")
        executable = runtime.get("executable")
        if not isinstance(profile, str) or not profile or not isinstance(executable, str):
            return
        try:
            binary = binary_for_profile(profile)
        except ValueError:
            return
        if not self._runtime_matches_current_host(binary):
            return
        if runtime.get("platform") != binary.platform:
            return
        accelerator = runtime.get("accelerator")
        if accelerator == "cpu" and binary.accelerator != "cpu":
            binary = replace(binary, accelerator="cpu", runtime=None)
        elif accelerator != binary.accelerator:
            return
        release_tag = runtime.get("version")
        archive_filename = runtime.get("archive_filename")
        archive_bytes = runtime.get("archive_bytes")
        archive_sha256 = runtime.get("archive_sha256")
        if (
            isinstance(release_tag, str)
            and re.fullmatch(r"b\d+", release_tag)
            and isinstance(archive_filename, str)
            and archive_filename
            and isinstance(archive_bytes, int)
            and not isinstance(archive_bytes, bool)
            and archive_bytes > 0
            and isinstance(archive_sha256, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", archive_sha256)
        ):
            binary = replace(
                binary,
                release_tag=release_tag,
                archive_filename=archive_filename,
                archive_bytes=archive_bytes,
                archive_sha256=archive_sha256.lower(),
                archive_members=tuple(
                    member.replace(binary.release_tag, release_tag, 1)
                    for member in binary.archive_members
                ),
            )
        server_path = Path(executable).expanduser().resolve()
        if not server_path.is_file():
            return
        # Verify the persisted runtime still has the selected platform executable.
        if binary.engine_name and server_path.name != binary.engine_name:
            return
        self._verify_manifest_archive(runtime, binary)
        libs = runtime["shared_libraries"]
        missing_libs = any(not Path(lib).expanduser().resolve().is_file() for lib in libs)
        if missing_libs and binary.platform.startswith("windows-"):
            # Windows relies on sibling DLLs; if they are absent the manifest is stale.
            return
        if not self._has_required_runtime_companions(binary, server_path.parent):
            return
        self._binary_spec = binary
        self._binary_path = server_path

    def _verify_manifest_archive(self, runtime: dict[str, Any], binary: Any) -> None:
        """Validate a recorded archive when it is still present on disk."""
        archive_path = runtime.get("archive_path")
        if not archive_path:
            return
        archive = Path(archive_path).expanduser().resolve()
        if not archive.is_file():
            return
        if binary.archive_bytes <= 0 or not re.fullmatch(r"[0-9a-fA-F]{64}", binary.archive_sha256):
            return
        try:
            self._verify_file(
                archive, binary.archive_bytes, binary.archive_sha256, "binary archive"
            )
        except LocalAIStateError:
            return

    @staticmethod
    def _has_required_runtime_companions(binary: Any, directory: Path) -> bool:
        for companion in binary.companions:
            if not all(
                (directory / Path(member).name).is_file() for member in companion.archive_members
            ):
                return False
            license_path = directory / companion.installed_license_filename
            try:
                license_bytes = license_path.read_bytes()
            except OSError:
                return False
            if license_path.is_symlink() or len(license_bytes) != companion.license_bytes:
                return False
            if hashlib.sha256(license_bytes).hexdigest() != companion.license_sha256:
                return False
        return True

    @staticmethod
    def _runtime_matches_current_host(binary: Any) -> bool:
        """Reject a portable runtime copied from a different OS/architecture."""
        host_os = platform.system().strip().lower()
        if host_os == "darwin":
            host_os = "macos"
        elif host_os.startswith("win"):
            host_os = "windows"
        host_arch = platform.machine().strip().lower().replace("-", "_")
        if host_arch in {"amd64", "x64", "x86_64"}:
            host_arch = "x86_64"
        elif host_arch in {"aarch64", "arm64"}:
            host_arch = "arm64"
        return binary.platform == f"{host_os}-{host_arch}"

    def _apply_manifest_models(self, models: Any) -> None:
        if not isinstance(models, dict):
            return
        for model_id, entry in models.items():
            if model_id not in MODELS or not isinstance(entry, dict):
                continue
            paths = self._manifest_model_paths(model_id, entry)
            main_path = paths.get("main")
            draft_path = paths.get("draft")
            if main_path and draft_path:
                self._model_paths[model_id] = main_path
                self._draft_paths[model_id] = draft_path

    def _manifest_model_paths(self, model_id: str, entry: dict[str, Any]) -> dict[str, Path | None]:
        from .catalog import MODELS as _MODELS

        spec = _MODELS.get(model_id)
        if spec is None:
            return {}
        result: dict[str, Path | None] = {}
        main_path_value = self._manifest_model_artifact_path(
            entry.get("main_model"), spec.model_filename
        )
        if main_path_value is not None:
            try:
                result["main"] = self._validated_model_file(Path(main_path_value), "main model")
            except LocalAIStateError:
                pass
        draft_path_value = self._manifest_model_artifact_path(
            entry.get("draft_model"), spec.draft_filename
        )
        if draft_path_value is not None:
            try:
                result["draft"] = self._validated_model_file(Path(draft_path_value), "draft model")
            except LocalAIStateError:
                pass
        return result

    @staticmethod
    def _manifest_model_artifact_path(entry: Any, filename: str) -> str | None:
        if not isinstance(entry, dict) or set(entry) != {"filename", "path", "bytes"}:
            return None
        if entry["filename"] != filename:
            return None
        path = entry["path"]
        size = entry["bytes"]
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            return None
        return path

    def _binary_spec_from_path(self, path: Path) -> Any:
        """Infer a hardware template from a deployed server path under llama.cpp."""
        try:
            resolved = path.expanduser().resolve()
            resolved.relative_to(self.local_dir)
        except (ValueError, RuntimeError):
            return None
        parts = resolved.parts
        if "llama.cpp" not in parts or not any(re.fullmatch(r"b\d+", part) for part in parts):
            return None
        for _profile, binary in BINARY_SPECS.items():
            if binary.platform in parts and resolved.name == binary.engine_name:
                return binary
        return None

    def _write_manifest(self) -> None:
        """Persist the current runtime, installed models, and active server config atomically."""
        with self._lock:
            manifest: dict[str, Any] = {
                "version": 1,
                "models": self._manifest_models(),
                "server_config": self._manifest_server_config(),
            }
            runtime = self._manifest_runtime()
            if runtime is not None:
                manifest["runtime"] = runtime
        temporary = self._manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        os.replace(temporary, self._manifest_path)

    def _write_manifest_if_enabled(self, enabled: bool) -> None:
        if enabled:
            self._write_manifest()

    def _manifest_runtime(self) -> dict[str, Any] | None:
        binary = self._binary_spec or (
            self._binary_spec_from_path(self._binary_path)
            if self._binary_path is not None
            else None
        )
        if binary is None or self._binary_path is None:
            return None
        server_path = self._binary_path
        archive_path = self._manifest_archive_path(binary)
        return {
            "profile": binary.profile,
            "platform": binary.platform,
            "accelerator": binary.accelerator,
            "version": binary.release_tag,
            "executable": str(server_path),
            "archive_path": archive_path,
            "archive_filename": binary.archive_filename,
            "archive_bytes": binary.archive_bytes,
            "archive_sha256": binary.archive_sha256,
            "shared_libraries": self._shared_libraries(server_path),
        }

    def _manifest_archive_path(self, binary: Any) -> str | None:
        if binary_archive_path is None:
            return None
        candidate = binary_archive_path(binary, root=self.local_dir)
        return str(candidate) if candidate.is_file() else None

    @staticmethod
    def _shared_libraries(server_path: Path) -> list[str]:
        if not server_path.is_file() or not server_path.parent.is_dir():
            return []
        return [
            str(child)
            for child in server_path.parent.iterdir()
            if child.suffix.lower() in {".dll", ".dylib", ".so"}
        ]

    def _manifest_server_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"port": self._configured_port, "cpu_threads": self._cpu_threads}
        if self._config is not None:
            model_id, context_tokens, mtp_enabled, mtp_draft_tokens = self._config
            config.update(
                {
                    "active_model_id": model_id,
                    "context_tokens": context_tokens,
                    "mtp_enabled": mtp_enabled,
                    "mtp_draft_tokens": mtp_draft_tokens,
                }
            )
        if self._port is not None:
            config["active_port"] = self._port
        if self._owner_pid is not None:
            config["owner_pid"] = self._owner_pid
        return config

    def _manifest_models(self) -> dict[str, Any]:
        return {
            model_id: entry
            for model_id in sorted(self._model_paths.keys() & self._draft_paths.keys())
            if (entry := self._manifest_model_entry(model_id)) is not None
        }

    def _manifest_model_entry(self, model_id: str) -> dict[str, Any] | None:
        from .catalog import MODELS as _MODELS

        spec = _MODELS.get(model_id)
        if spec is None:
            return None
        try:
            main = self._validated_model_file(self._model_paths[model_id], "main model")
            draft = self._validated_model_file(self._draft_paths[model_id], "draft model")
        except LocalAIStateError:
            return None
        return {
            "main_model": self._manifest_model_artifact(spec.model_filename, main),
            "draft_model": self._manifest_model_artifact(spec.draft_filename, draft),
        }

    @staticmethod
    def _manifest_model_artifact(filename: str, path: Path) -> dict[str, Any]:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return {"filename": filename, "path": str(path), "bytes": int(size)}

    def status(self) -> LocalAIStatus:
        with self._lock:
            self._reconcile_dead_process_locked()
            self._refresh_sleep_state_locked()
            operation = self._operation_status
            if operation is None:
                had_cached_runtime = self._binary_path is not None
                if (
                    not self._process_is_running()
                    and had_cached_runtime
                    and not self._runtime_available_locked()
                    and self._status.state in {"installed", "stopped", "error", "cancelled"}
                ):
                    self._status = LocalAIStatus(
                        state="not_installed", model_id=self._status.model_id
                    )
                return self._status
            lifecycle = self._status
            lifecycle_available = self._runtime_available_locked() and bool(self._model_paths)
            if lifecycle_available and lifecycle.state in {
                "not_installed",
                "downloading",
                "importing",
                "cancelling",
                "cancelled",
            }:
                lifecycle = self._idle_status_locked()
            if lifecycle_available or lifecycle.state in {"starting", "running", "sleeping"}:
                lifecycle_failure = lifecycle.state == "error"
                return replace(
                    lifecycle,
                    downloaded_bytes=operation.downloaded_bytes,
                    total_bytes=operation.total_bytes,
                    available_disk_bytes=operation.available_disk_bytes,
                    download_phase=operation.download_phase,
                    import_bytes=operation.import_bytes,
                    import_total=operation.import_total,
                    import_phase=operation.import_phase,
                    job_id=operation.job_id,
                    operation_kind=operation.operation_kind,
                    operation_state=operation.state,
                    operation_model_id=operation.model_id,
                    error_code=lifecycle.error_code if lifecycle_failure else operation.error_code,
                    message=lifecycle.message if lifecycle_failure else operation.message,
                )
            return replace(
                operation,
                operation_kind=operation.operation_kind,
                operation_state=operation.state,
                operation_model_id=operation.model_id,
            )

    def _reconcile_dead_process_locked(self) -> None:
        """Turn a later child crash into a retryable, observable error state."""
        process = self._process
        if process is None or process.poll() is None:
            return
        if self._status.state not in {"starting", "running", "sleeping"}:
            return
        model_id = self._status.model_id
        self._record_startup_diagnostic("process_exited", process, self._process_command)
        self._clear_owned_process_locked(remove_marker=True)
        self._start_in_flight = None
        self._status = LocalAIStatus(
            state="error",
            model_id=model_id,
            error_code="process_exited",
            message="Integrated AI service exited",
        )

    def _idle_status_locked(self) -> LocalAIStatus:
        """Return the normal idle status after a completed cancelled job.

        Cancellation is a transient request, not a durable product state. A
        verified runtime and model remain ready to start; otherwise the next
        meaningful action is choosing a model to download.
        """
        if self._runtime_available_locked() and self._model_paths:
            return LocalAIStatus(state="installed")
        return LocalAIStatus(state="not_installed")

    def _runtime_available_locked(self) -> bool:
        path = self._binary_path
        if path is None or not path.is_file():
            if path is not None:
                self._binary_path = None
                self._binary_spec = None
                self._runtime_probe = RuntimeProbe("failed")
                self._runtime_device = None
                self._runtime_offload_verified = False
                self._runtime_offloaded_layers = 0
                self._cpu_fallback_confirmed = False
            return False
        return True

    def _refresh_sleep_state_locked(self) -> None:
        if (
            self._status.state != "running"
            or not self._process_is_running()
            or self._active_requests
            or self._last_request_idle_at is None
            or time.monotonic() - self._last_request_idle_at < IDLE_SLEEP_SECONDS
        ):
            return
        self._status = replace(self._status, state="sleeping")

    def set_install_completion_callback(self, callback: Callable[[str], None]) -> None:
        """Register the application callback invoked after a verified model install."""
        with self._lock:
            self._install_completion_callback = callback

    def set_auto_start_completion_callback(self, callback: Callable[[LocalAIStatus], None]) -> None:
        """Register application integration after an install starts the server."""
        with self._lock:
            self._auto_start_completion_callback = callback

    def inventory(self) -> list[dict[str, Any]]:
        """Return an application-owned, path-safe inventory of catalog models.

        Installed state and byte sizes derive **only** from paths that pass
        :meth:`_validated_model_file` (final, non-empty, non-symlink,
        in-root).  A model is reported as installed only when **both** the
        main and draft artifacts are valid; if either fails, the entry is
        reported as ``installed=False`` with ``integrity='unknown'`` and
        **no** byte sizes — a ``.part`` placeholder, a zero-byte file, a
        symlink, or an external path must not leak partial-install
        information.  Invalid cached entries are dropped from the
        registries so subsequent calls do not re-validate them.  The
        application mapper already strips ``model_path``/``draft_path``
        from the payload sent to the browser.
        """
        with self._lock:
            result = []
            for model_id in MODELS:
                validated_main = self._cached_or_discovered_model_path(model_id, draft=False)
                validated_draft = self._cached_or_discovered_model_path(model_id, draft=True)
                installed = validated_main is not None and validated_draft is not None
                # Atomically verified: only surface byte counts when the
                # whole model (main + draft) passes validation.  Reporting
                # one side's bytes when the other is invalid would imply
                # a half-install that the on-disk state does not justify.
                entry = {
                    "model_id": model_id,
                    "installed": installed,
                    "integrity": "verified" if installed else "unknown",
                    "model_path": str(validated_main) if installed else None,
                    "draft_path": str(validated_draft) if installed else None,
                    "model_bytes": self._safe_size(validated_main) if installed else None,
                    "draft_bytes": self._safe_size(validated_draft) if installed else None,
                }
                result.append(entry)
            return result

    def _cached_or_discovered_model_path(self, model_id: str, *, draft: bool) -> Path | None:
        """Return a verified final model/draft path from cache or on-disk discovery.

        Tries the in-memory cache first (dropping invalid entries on
        failure) and, on a miss, falls back to the catalog-rooted
        candidate.  The returned path always passes
        :meth:`_validated_model_file` (regular, non-empty, non-symlink,
        no ``.part`` streaming placeholder, contained in ``local_dir``).
        Returns ``None`` if no valid on-disk artifact exists; a half
        install must not surface a single side as installed.
        """
        paths = self._draft_paths if draft else self._model_paths
        label = "draft model" if draft else "main model"
        cached = paths.get(model_id)
        if cached is not None:
            try:
                return self._validated_model_file(cached, label)
            except LocalAIStateError:
                paths.pop(model_id, None)
                return None
        spec = MODELS.get(model_id)
        if spec is None:
            return None
        filename = spec.draft_filename if draft else spec.model_filename
        candidate = self.local_dir / "models" / model_id / filename
        try:
            validated = self._validated_model_file(candidate, label)
        except LocalAIStateError:
            return None
        paths[model_id] = validated
        return validated

    def _validate_cached_path(
        self,
        cached: Path | None,
        label: str,
        registry: dict[str, Path],
        model_id: str,
    ) -> Path | None:
        """Validate a cached model/draft path; drop the cache on failure.

        Returns the validated path on success, or ``None`` if the path is
        absent or fails :meth:`_validated_model_file`.  The caller uses
        the returned path's ``stat().st_size`` for byte counts; an invalid
        or missing entry contributes no byte count.
        """
        if cached is None:
            return None
        try:
            return self._validated_model_file(cached, label)
        except LocalAIStateError:
            registry.pop(model_id, None)
            return None

    @staticmethod
    def _safe_size(path: Path | None) -> int | None:
        if path is None:
            return None
        try:
            return int(path.stat().st_size)
        except OSError:
            return None

    def runtime_details(self) -> dict[str, Any]:
        """Return only privacy-safe diagnostics for the management UI."""
        with self._lock:
            return dict(self._last_diagnostic)

    def read_runtime_selection_record(self) -> bytes | None:
        """Read only the fixed, bounded selection file for schema validation by the API."""
        if self._selection_diagnostics_path.is_symlink():
            raise ValueError("invalid runtime selection record")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self._selection_diagnostics_path, flags)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as record:
            metadata = os.fstat(record.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 8192:
                raise ValueError("invalid runtime selection record")
            content = record.read(8193)
            if len(content) > 8192:
                raise ValueError("invalid runtime selection record")
            return content

    def _begin_runtime_selection(self, operation: str) -> None:
        # Record only catalog identities and fixed failure categories. Child output,
        # hardware names, paths, prompts, and credentials never enter this file.
        self._selection_record = {
            "version": 1,
            "operation": operation,
            "outcome": "incomplete",
            "attempts": [],
        }
        self._persist_runtime_selection()

    def _record_runtime_selection(
        self, binary: Any, stage: str, result: str, reason: str | None = None
    ) -> None:
        record = self._selection_record
        if record is None:
            return
        attempts = record["attempts"]
        if len(attempts) < 12:
            entry = {"profile": binary.profile, "stage": stage, "result": result}
            if reason in {
                "missing_runtime_library",
                "driver_unavailable",
                "no_gpu",
                "probe_timeout",
                "probe_failed",
                "malformed_output",
                "model_offload_failed",
                "runtime_launch_failed",
                "runtime_options_unavailable",
                "runtime_incompatible",
                "accelerator_failed",
                "insufficient_resources",
                "port_conflict",
            }:
                entry["reason"] = reason
            attempts.append(entry)
        if result == "selected":
            record["selected_profile"] = binary.profile
            record["outcome"] = "selected"
        self._persist_runtime_selection()

    def _persist_runtime_selection(self) -> None:
        if self._selection_record is None:
            return
        try:
            temporary = self._selection_diagnostics_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._selection_record), encoding="utf-8")
            os.replace(temporary, self._selection_diagnostics_path)
        except OSError:
            pass

    def runtime_capability_state(self) -> str:
        """Return capability proven by the installed executable, never hardware hints."""
        with self._lock:
            if self._runtime_offload_verified:
                return "gpu_verified"
            if (
                self._cpu_fallback_confirmed
                and self._binary_spec is not None
                and getattr(self._binary_spec, "accelerator", "cpu") == "cpu"
            ):
                return "cpu_confirmed"
            return "unknown"

    def configured_command_reference(
        self,
        model_id: str,
        *,
        context_tokens: int,
        mtp_enabled: bool,
        mtp_draft_tokens: int = DEFAULT_MTP_DRAFT_TOKENS,
    ) -> str | None:
        """Return the active or next-start command with managed paths redacted.

        This diagnostic accessor must stay side-effect free. In particular, it
        must not launch ``llama-server --list-devices`` while holding the
        lifecycle lock because a slow or wedged optional probe would otherwise
        block status and start requests.
        """
        with self._lock:
            if self._process_is_running() and self._process_command is not None:
                return self._command_reference(self._process_command)
            try:
                model = self._model(model_id)
                context_tokens = self._validated_start_options(
                    model, context_tokens, mtp_enabled, mtp_draft_tokens
                )
                binary_path = self._resolve_binary_path()
                model_path = self._model_path(model_id, draft=False)
                draft_path = self._model_path(model_id, draft=True)
                self._validate_artifacts(model_id, binary_path, model_path, draft_path)
                command = self._build_command(
                    binary_path=binary_path,
                    model=model,
                    model_path=model_path,
                    draft_path=draft_path,
                    context_tokens=context_tokens,
                    mtp_enabled=mtp_enabled,
                    mtp_draft_tokens=mtp_draft_tokens,
                    accelerator_available=self._accelerator_value(),
                    runtime_device=self._runtime_device_for_reference(),
                    port=self._configured_port,
                )
                if self._configured_port == 0:
                    command[command.index("--port") + 1] = "<available-loopback-port>"
            except (LocalAIStateError, OSError, ValueError):
                return None
            return self._command_reference(command)

    def _runtime_device_for_reference(self) -> str:
        """Use only cached runtime evidence when rendering diagnostics."""
        accelerated = bool(
            self._binary_spec and getattr(self._binary_spec, "accelerator", "cpu") != "cpu"
        )
        if not accelerated:
            return "none"
        identifiers = tuple(device.identifier for device in self._runtime_probe.devices)
        if not identifiers:
            raise LocalAIStateError(
                "Integrated AI accelerator has not been probed", code="accelerator_failed"
            )
        return self._runtime_device if self._runtime_device in identifiers else identifiers[0]

    def _load_startup_diagnostic(self) -> None:
        try:
            payload = json.loads(self._diagnostics_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        code = payload.get("error_code")
        exit_code = payload.get("exit_code")
        tail = payload.get("log_tail")
        offloaded_layers = payload.get("observed_offloaded_layers")
        command_reference = self.safe_command_reference(payload.get("command_reference"))
        valid_error = (
            isinstance(code, str)
            and re.fullmatch(r"[a-z_]{3,64}", code)
            and (exit_code is None or isinstance(exit_code, int))
            and isinstance(tail, list)
            and all(
                isinstance(line, str) and self._safe_diagnostic_line(line) == line for line in tail
            )
        )
        if command_reference is not None or valid_error:
            self._last_diagnostic = {
                "command_reference": command_reference,
                "error_code": code if valid_error else None,
                "exit_code": exit_code if valid_error and isinstance(exit_code, int) else None,
                "log_tail": tail[-12:] if valid_error else [],
                "observed_offloaded_layers": (
                    offloaded_layers
                    if isinstance(offloaded_layers, int)
                    and not isinstance(offloaded_layers, bool)
                    and offloaded_layers >= 0
                    else 0
                ),
            }

    @staticmethod
    def safe_command_reference(value: Any) -> str | None:
        if not isinstance(value, str) or not value or len(value) > 2000:
            return None
        if any(token in value for token in ("/", "\\", "http:", "https:", "\n", "\r")):
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.:<>= -]+", value):
            return None
        if value.split(maxsplit=1)[0] not in {"llama-server", "llama-server.exe"}:
            return None
        return value

    @classmethod
    def _command_reference(cls, command: list[str]) -> str | None:
        if not command:
            return None
        redacted = list(command)
        redacted[0] = re.split(r"[/\\]", redacted[0])[-1]
        for option, placeholder in (
            ("--model", "<managed-main-model>"),
            ("--model-draft", "<managed-mtp-draft>"),
        ):
            if option in redacted:
                value_index = redacted.index(option) + 1
                if value_index < len(redacted):
                    redacted[value_index] = placeholder
        return cls.safe_command_reference(" ".join(redacted))

    @staticmethod
    def _safe_diagnostic_line(value: Any) -> str | None:
        text = " ".join(str(value).split())
        if not text or len(text) > 240:
            return None
        if any(token in text for token in ("/", "\\", "http:", "https:", "--")):
            return None
        # Llama output can include model paths and user/provider text. Retain only
        # concise failure evidence, never arbitrary child output.
        if not re.search(
            r"error|fail|missing|denied|permission|library|memory|unsupported|cannot", text, re.I
        ):
            return None
        return text

    def _record_startup_diagnostic(
        self, code: str, process: Any = None, command: list[str] | None = None
    ) -> None:
        exit_code = None
        try:
            value = process.poll() if process is not None else None
            exit_code = value if isinstance(value, int) else None
        except (AttributeError, OSError):
            pass
        tail = [
            line for line in (self._safe_diagnostic_line(line) for line in self._log_lines) if line
        ]
        diagnostic = {
            "command_reference": self._command_reference(command or []),
            "error_code": code,
            "exit_code": exit_code,
            "log_tail": tail[-12:],
        }
        self._persist_startup_diagnostic(diagnostic)

    def _record_successful_start(self, command: list[str], offloaded_layers: int) -> None:
        self._persist_startup_diagnostic(
            {
                "command_reference": self._command_reference(command),
                "error_code": None,
                "exit_code": None,
                "log_tail": [],
                "observed_offloaded_layers": max(0, offloaded_layers),
            }
        )

    def _persist_startup_diagnostic(self, diagnostic: dict[str, Any]) -> None:
        self._last_diagnostic = diagnostic
        try:
            temporary = self._diagnostics_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(diagnostic), encoding="utf-8")
            os.replace(temporary, self._diagnostics_path)
        except OSError:
            # Diagnostics cannot turn a retryable lifecycle failure into a crash.
            pass

    def mark_request_active(self, expected_model_id: str | None = None) -> None:
        """Atomically acquire request ownership for the running managed model.

        ``expected_model_id`` closes the gap between an earlier status check and
        request setup. The zero-argument form remains suitable for provider
        callbacks that are already bound to the active managed runtime.
        """
        if expected_model_id is not None and (
            not isinstance(expected_model_id, str) or not expected_model_id
        ):
            raise ValueError("expected_model_id must be a non-empty string")
        with self._lock:
            self._reconcile_dead_process_locked()
            running_model_id = self._config[0] if self._config is not None else None
            if (
                not self._process_is_running()
                or self._status.state not in {"running", "sleeping"}
                or running_model_id is None
                or self._status.model_id != running_model_id
            ):
                raise LocalAIStateError("Integrated AI is not running", code="local_ai_not_running")
            if expected_model_id is not None and running_model_id != expected_model_id:
                raise LocalAIStateError(
                    "the expected Integrated AI model is not running",
                    code="local_ai_wrong_model_running",
                )
            self._active_requests += 1
            if self._status.state == "sleeping":
                self._status = replace(self._status, state="running")

    def mark_request_idle(self) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            if self._active_requests == 0 and self._process_is_running():
                self._last_request_idle_at = time.monotonic()

    def _guard_start_against_operation_locked(
        self, model_id: str, install_job_id: str | None = None
    ) -> None:
        operation = self._operation_status
        if operation is None:
            return
        if install_job_id is not None and operation.job_id == install_job_id:
            return
        if operation.operation_kind == "runtime_update" and operation.state in {
            "downloading",
            "cancelling",
        }:
            raise LocalAIStateError(
                "cannot start Local AI while the runtime is being updated",
                code="state_conflict",
            )
        if operation.model_id == model_id and operation.state in {
            "downloading",
            "importing",
            "cancelling",
        }:
            raise LocalAIStateError(
                "cannot start a model while its files are being acquired",
                code="state_conflict",
            )

    def _assert_start_completed_locked(self, desired: tuple[Any, ...], process: Any) -> None:
        if (
            self._start_in_flight != desired
            or self._process is not process
            or process.poll() is not None
        ):
            raise LocalAIStateError("Integrated AI startup was interrupted", code="state_conflict")

    def start(
        self,
        model_id: str,
        *,
        context_tokens: int | None = None,
        mtp_enabled: bool = False,
        mtp_draft_tokens: int = DEFAULT_MTP_DRAFT_TOKENS,
        _install_job_id: str | None = None,
        _persist_manifest: bool = True,
    ) -> LocalAIStatus:
        """Start or safely restart the configured local server."""
        model = self._model(model_id)
        context_tokens = self._validated_start_options(
            model, context_tokens, mtp_enabled, mtp_draft_tokens
        )
        desired = (model_id, context_tokens, mtp_enabled, mtp_draft_tokens)

        with self._lock:
            self._guard_start_against_operation_locked(model_id, _install_job_id)
            if self._active_requests:
                raise LocalAIStateError("cannot start or restart while a request is active")
            if self._start_in_flight is not None:
                raise LocalAIStateError("Integrated AI is already starting", code="busy")
            if self._process_is_running() and self._config == desired:
                return self.status()
            if self._process is not None:
                self._stop_locked()
            self._reconcile_owner_marker()

            model_path = self._model_path(model_id, draft=False)
            draft_path = self._model_path(model_id, draft=True)
            binary_path = self._resolve_binary_path()
            self._validate_artifacts(model_id, binary_path, model_path, draft_path)
            port = self._reserve_loopback_port()
            self._port = port
            accelerator = self._accelerator_value()
            runtime_device = self._runtime_device_for_start(binary_path)
            command = self._build_command(
                binary_path=binary_path,
                model=model,
                model_path=model_path,
                draft_path=draft_path,
                context_tokens=context_tokens,
                mtp_enabled=mtp_enabled,
                mtp_draft_tokens=mtp_draft_tokens,
                accelerator_available=accelerator,
                runtime_device=runtime_device,
                port=port,
            )
            self._status = LocalAIStatus(
                state="starting",
                model_id=model_id,
                context_tokens=context_tokens,
                mtp_enabled=mtp_enabled,
                mtp_draft_tokens=mtp_draft_tokens if mtp_enabled else None,
                port=port,
                host=f"http://{LOCAL_HOST}:{port}",
                accelerator=model.flash_attention if accelerator else "cpu",
            )
            self._start_in_flight = desired
            try:
                self._log_lines.clear()
                self._process = self._spawn(command)
                process = self._process
                self._process_command = command
                self._owner_pid = int(process.pid)
                self._write_owner_marker(binary_path, port)
                self._write_manifest_if_enabled(_persist_manifest)
                self._start_log_reader(process)
            except Exception as exc:
                code = (
                    exc.code
                    if isinstance(exc, LocalAIStateError)
                    else self._classify_startup_error(exc)
                )
                self._record_startup_diagnostic(code, self._process, command)
                # Marker publication can fail after Popen. That child is still
                # unquestionably ours, so do not require a marker to clean it up.
                self._stop_spawned_process_locked()
                message = self._safe_error(exc, "server did not become ready")
                self._status = LocalAIStatus(
                    state="error", model_id=model_id, error_code=code, message=message
                )
                self._start_in_flight = None
                if code == "artifact_invalid":
                    self._quarantine_model_pair(model_id)
                if isinstance(exc, LocalAIStateError):
                    raise
                raise LocalAIStateError(message, code=code) from exc

        # Health polling can take up to the startup timeout. Keep it outside the
        # manager lock so status, transfer progress, and cancellation remain
        # responsive while the child initializes.
        try:
            server_model_name = self._poll_health(port)
            offloaded_layers = self._wait_for_gpu_offload(process) if accelerator else 0
            if (
                self._binary_spec is not None
                and getattr(self._binary_spec, "accelerator", "cpu") != "cpu"
                and offloaded_layers <= 0
            ):
                raise LocalAIStateError(
                    "Integrated AI did not verify GPU layer offload",
                    code="accelerator_failed",
                    selection_reason="model_offload_failed",
                )
        except Exception as exc:
            with self._lock:
                if self._start_in_flight != desired or self._process is not process:
                    raise LocalAIStateError(
                        "Integrated AI startup was interrupted", code="state_conflict"
                    ) from exc
                code = (
                    exc.code
                    if isinstance(exc, LocalAIStateError)
                    else self._classify_startup_error(exc)
                )
                self._record_startup_diagnostic(code, process, command)
                self._stop_spawned_process_locked()
                message = self._safe_error(exc, "server did not become ready")
                self._status = LocalAIStatus(
                    state="error", model_id=model_id, error_code=code, message=message
                )
                self._start_in_flight = None
                if code == "artifact_invalid":
                    self._quarantine_model_pair(model_id)
            if isinstance(exc, LocalAIStateError):
                raise
            raise LocalAIStateError(message, code=code) from exc

        with self._lock:
            self._reconcile_dead_process_locked()
            self._assert_start_completed_locked(desired, process)
            self._config = desired
            self._server_model_name = server_model_name
            self._port = port
            self._status = LocalAIStatus(
                state="running",
                model_id=model_id,
                model_name=server_model_name,
                host=f"http://{LOCAL_HOST}:{port}",
                port=port,
                context_tokens=context_tokens,
                mtp_enabled=mtp_enabled,
                mtp_draft_tokens=mtp_draft_tokens if mtp_enabled else None,
                accelerator="gpu" if accelerator else "cpu",
            )
            self._runtime_offload_verified = bool(accelerator)
            self._runtime_offloaded_layers = offloaded_layers if accelerator else 0
            self._last_request_idle_at = time.monotonic()
            self._start_in_flight = None
            self._record_successful_start(command, self._runtime_offloaded_layers)
            self._write_manifest_if_enabled(_persist_manifest)
        return self.status()

    def _observed_gpu_offload(self) -> bool:
        """Require a positive layer count from the real model-loading startup."""
        return self._observed_gpu_offload_layers() > 0

    def _observed_gpu_offload_layers(self) -> int:
        """Return the positive layer count reported by the real model load."""
        patterns = (
            r"offload(?:ed|ing)\s+([1-9][0-9]*)\b.*\blayer",
            r"offloaded\s+([1-9][0-9]*)\s*/\s*[1-9][0-9]*\s+layers",
        )
        counts = (
            int(match.group(1))
            for line in tuple(self._log_lines)
            for pattern in patterns
            if (match := re.search(pattern, line, re.IGNORECASE)) is not None
        )
        return max(counts, default=0)

    def _wait_for_gpu_offload(self, process: Any) -> int:
        """Let the asynchronous log reader catch up after health becomes ready."""
        deadline = time.monotonic() + RUNTIME_OFFLOAD_LOG_GRACE_SECONDS
        while True:
            layers = self._observed_gpu_offload_layers()
            if layers > 0 or process.poll() is not None or time.monotonic() >= deadline:
                return layers
            time.sleep(min(0.01, self._health_interval or 0.01))

    @staticmethod
    def _validated_start_options(
        model: Any,
        context_tokens: int | None,
        mtp_enabled: bool,
        mtp_draft_tokens: int,
    ) -> int:
        selected_context = DEFAULT_CONTEXT_TOKENS if context_tokens is None else context_tokens
        if (
            not isinstance(selected_context, int)
            or isinstance(selected_context, bool)
            or selected_context < MIN_CONTEXT_TOKENS
            or selected_context > model.supported_context_tokens
        ):
            raise ValueError(
                "context_tokens must be an integer between 8192 and "
                f"{model.supported_context_tokens}"
            )
        if not isinstance(mtp_enabled, bool):
            raise ValueError("mtp_enabled must be a boolean")
        if mtp_draft_tokens not in MTP_DRAFT_TOKEN_CHOICES:
            raise ValueError("mtp_draft_tokens must be between 1 and 6")
        return selected_context

    def stop(self) -> bool:
        with self._lock:
            if self._active_requests:
                raise LocalAIStateError(
                    "cannot stop Integrated AI while a request is active",
                    code="state_conflict",
                )
            return self._stop_locked()

    def shutdown(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                job.cancel_event.set()
            for job in self._background_import_jobs.values():
                job.cancel_event.set()
            self._stop_locked()

    def install(
        self,
        model_id: str,
        *,
        start_after_install: bool,
        context_tokens: int | None = None,
        mtp_enabled: bool = False,
        mtp_draft_tokens: int = DEFAULT_MTP_DRAFT_TOKENS,
    ) -> str:
        model = self._model(model_id)
        if not isinstance(start_after_install, bool):
            raise ValueError("start_after_install must be a boolean")
        context_tokens = self._validated_start_options(
            model, context_tokens, mtp_enabled, mtp_draft_tokens
        )
        with self._lock:
            if self._process_is_running() and start_after_install:
                raise LocalAIStateError(
                    "cannot replace the running model after download", code="state_conflict"
                )
            if (
                self._process_is_running()
                and self._config is not None
                and self._config[0] == model_id
            ):
                raise LocalAIStateError("model is currently active", code="state_conflict")
            if self._start_in_flight is not None and self._start_in_flight[0] == model_id:
                raise LocalAIStateError("model is currently starting", code="state_conflict")
            if self._imports or self._background_import_jobs:
                raise LocalAIStateError("a model import is already in progress")
            if any(job.cancel_event.is_set() is False for job in self._jobs.values()):
                raise LocalAIStateError("an installation is already in progress")
            job_id = uuid.uuid4().hex
            job = _InstallJob(
                job_id,
                model_id,
                start_after_install,
                threading.Event(),
                context_tokens=context_tokens,
                mtp_enabled=mtp_enabled,
                mtp_draft_tokens=mtp_draft_tokens,
            )
            self._jobs[job_id] = job
            self._operation_status = LocalAIStatus(
                state="downloading",
                model_id=model_id,
                job_id=job_id,
                operation_kind="model_download",
                download_phase="preparing",
            )
            thread = threading.Thread(
                target=self._run_install_job_wrapper, args=(job,), daemon=True
            )
            thread.start()
            return job_id

    def cancel_install(self, job_id: str) -> LocalAIStatus:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise LocalAIStateError("unknown installation job")
            job.cancel_event.set()
            next_status = LocalAIStatus(
                state="cancelling",
                model_id=job.model_id,
                job_id=job.job_id,
                operation_kind=(
                    "runtime_update" if job.model_id == "__runtime_update__" else "model_download"
                ),
                message="cancellation requested",
            )
            self._operation_status = next_status
            return self.status()

    def begin_import(self, model_id: str) -> _ImportSession:
        """Reserve private staging paths for a complete main+draft import.

        The HTTP layer writes only to the returned ``.part`` files.  Nothing
        is visible as an installed model until :meth:`finish_import` validates
        both artifacts and publishes them together.
        """
        self._model(model_id)
        with self._lock:
            if self._jobs:
                raise LocalAIStateError("an installation is already in progress")
            if self._imports or self._background_import_jobs:
                raise LocalAIStateError("an import is already in progress")
            if any(
                entry.get("model_id") == model_id and entry.get("installed")
                for entry in self.inventory()
            ):
                raise LocalAIStateError(
                    "model is already installed", code="model_already_installed"
                )
            if any(session.model_id == model_id for session in self._imports.values()):
                raise LocalAIStateError("an import for this model is already in progress")
            # Staging areas are never an inventory source.  Clear every stale
            # import artifact before allocating the one and only active session.
            self._clear_import_artifacts_locked()
            import_id = uuid.uuid4().hex
            directory = self.local_dir / ".imports" / import_id
            directory.mkdir(parents=True, exist_ok=False)
            session = _ImportSession(
                import_id=import_id,
                model_id=model_id,
                directory=directory,
                main_part=directory / "main.part",
                draft_part=directory / "draft.part",
            )
            self._imports[import_id] = session
            self._operation_status = LocalAIStatus(
                state="importing",
                model_id=model_id,
                job_id=import_id,
                operation_kind="model_import",
                import_phase="copying",
            )
            return session

    def _clear_import_artifacts_locked(self) -> None:
        """Remove abandoned import staging directories below our owned root."""
        root = self.local_dir / ".imports"
        try:
            if root.exists():
                shutil.rmtree(root)
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LocalAIStateError("could not clear stale import artifacts") from exc

    def start_background_import(self, model_id: str, source_root: Path | str) -> str:
        """Copy a verified pair from a user-selected portable bundle."""
        source_main, source_draft = self._import_source_paths(model_id, Path(source_root))
        session = self.begin_import(model_id)
        job = _BackgroundImportJob(
            job_id=session.import_id,
            session=session,
            source_main=source_main,
            source_draft=source_draft,
            cancel_event=threading.Event(),
        )
        with self._lock:
            # ``begin_import`` reserved the global import slot.  Do not allow
            # a race between that reservation and the worker registration.
            if session.import_id not in self._imports:
                raise LocalAIStateError("model import could not be reserved")
            self._background_import_jobs[job.job_id] = job
            total = self._source_pair_size(source_main, source_draft)
            self._operation_status = LocalAIStatus(
                state="importing",
                model_id=model_id,
                job_id=job.job_id,
                operation_kind="model_import",
                import_total=total or 0,
                import_phase="copying",
            )
        threading.Thread(
            target=self._run_background_import_wrapper, args=(job,), daemon=True
        ).start()
        return job.job_id

    def start_detected_background_import(self, source_root: Path | str) -> tuple[str, str]:
        """Recognize and import the single complete catalog model below a selected root."""
        selected_root = Path(source_root)
        try:
            root = selected_root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise LocalAIStateError(
                "selected import directory is unavailable", code="model_import_unavailable"
            ) from exc
        if not root.is_dir():
            raise LocalAIStateError(
                "selected import directory is unavailable", code="model_import_unavailable"
            )

        matches: list[str] = []
        for model_id in MODELS:
            try:
                self._import_source_paths(model_id, root)
            except LocalAIStateError:
                continue
            matches.append(model_id)

        if not matches:
            raise LocalAIStateError(
                "selected directory contains no compatible complete model pair",
                code="model_import_not_found",
            )
        if len(matches) > 1:
            raise LocalAIStateError(
                "selected directory contains multiple complete models; choose one model folder",
                code="model_import_ambiguous",
            )
        model_id = matches[0]
        return self.start_background_import(model_id, root), model_id

    def _import_source_paths(self, model_id: str, selected_root: Path) -> tuple[Path, Path]:
        """Locate the exact catalog pair under an explicit user-selected root."""
        model = self._model(model_id)
        try:
            root = selected_root.expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise LocalAIStateError(
                "selected import directory is unavailable", code="model_import_unavailable"
            ) from exc
        candidates = (
            root,
            root / "models" / model_id,
            root / "local-ai" / "models" / model_id,
            root / ".aqa" / "local-ai" / "models" / model_id,
        )
        for directory in candidates:
            main = directory / model.model_filename
            draft = directory / model.draft_filename
            if (
                main.is_file()
                and draft.is_file()
                and not main.is_symlink()
                and not draft.is_symlink()
            ):
                return main.resolve(), draft.resolve()
        raise LocalAIStateError(
            "selected directory contains no compatible complete model pair",
            code="model_import_not_found",
        )

    def _run_background_import_wrapper(self, job: _BackgroundImportJob) -> None:
        try:
            self._copy_import_artifact(job, job.source_main, job.session.main_part)
            self._copy_import_artifact(job, job.source_draft, job.session.draft_part)
            if job.cancel_event.is_set():
                raise LocalAIStateError("model import cancelled")
            with self._lock:
                self._operation_status = LocalAIStatus(
                    state="importing",
                    model_id=job.session.model_id,
                    job_id=job.job_id,
                    operation_kind="model_import",
                    import_bytes=self._source_pair_size(job.source_main, job.source_draft),
                    import_total=self._source_pair_size(job.source_main, job.source_draft),
                    import_phase="verifying",
                )
            self.finish_import(job.job_id)
        except Exception as exc:
            self.abort_import(job.job_id)
            with self._lock:
                if job.cancel_event.is_set():
                    self._operation_status = None
                    if not self._process_is_running():
                        self._status = self._idle_status_locked()
                else:
                    self._operation_status = LocalAIStatus(
                        state="error",
                        model_id=job.session.model_id,
                        job_id=job.job_id,
                        operation_kind="model_import",
                        message=self._safe_error(exc, "model import failed"),
                    )
        finally:
            with self._lock:
                self._background_import_jobs.pop(job.job_id, None)

    def _copy_import_artifact(
        self, job: _BackgroundImportJob, source: Path, destination: Path
    ) -> None:
        completed_before = (
            (self._safe_size(job.source_main) or 0) if source == job.source_draft else 0
        )
        total = self._source_pair_size(job.source_main, job.source_draft)
        copied = 0
        try:
            with source.open("rb") as input_stream, destination.open("xb") as output_stream:
                while chunk := input_stream.read(1024 * 1024):
                    if job.cancel_event.is_set():
                        raise LocalAIStateError("model import cancelled")
                    output_stream.write(chunk)
                    copied += len(chunk)
                    with self._lock:
                        self._operation_status = LocalAIStatus(
                            state="importing",
                            model_id=job.session.model_id,
                            job_id=job.job_id,
                            operation_kind="model_import",
                            import_bytes=completed_before + copied,
                            import_total=total,
                            import_phase="copying",
                        )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def _source_pair_size(self, main: Path, draft: Path) -> int:
        return (self._safe_size(main) or 0) + (self._safe_size(draft) or 0)

    def cancel_import(self, job_id: str) -> LocalAIStatus:
        with self._lock:
            job = self._background_import_jobs.get(job_id)
            if job is None:
                raise LocalAIStateError("unknown model import")
            job.cancel_event.set()
            self._operation_status = LocalAIStatus(
                state="cancelling",
                model_id=job.session.model_id,
                job_id=job_id,
                operation_kind="model_import",
                message="cancellation requested",
            )
            return self.status()

    def import_part_path(self, import_id: str, artifact: str) -> Path:
        with self._lock:
            session = self._imports.get(import_id)
            if session is None or artifact not in {"main", "draft"}:
                raise LocalAIStateError("unknown model import")
            return session.main_part if artifact == "main" else session.draft_part

    def abort_import(self, import_id: str) -> None:
        with self._lock:
            session = self._imports.get(import_id)
        if session is not None:
            shutil.rmtree(session.directory, ignore_errors=True)
        with self._lock:
            if self._imports.get(import_id) is session:
                self._imports.pop(import_id, None)
            if self._operation_status is not None and self._operation_status.job_id == import_id:
                self._operation_status = None

    def finish_import(self, import_id: str) -> None:
        """Validate and atomically publish a staged pair into the catalog tree."""
        completion_callback: Callable[[str], None] | None = None
        completed_model_id: str | None = None
        with self._lock:
            session = self._imports.get(import_id)
            if session is None:
                raise LocalAIStateError("unknown model import")
            if self._jobs:
                raise LocalAIStateError("Local AI changed state during model import")
            try:
                self._publish_import_locked(session)
                completion_callback = self._install_completion_callback
                completed_model_id = session.model_id
                if self._operation_status is not None:
                    if self._operation_status.job_id == import_id:
                        self._operation_status = None
            except Exception as exc:
                self._operation_status = LocalAIStatus(
                    state="error",
                    model_id=session.model_id,
                    job_id=import_id,
                    operation_kind="model_import",
                    message=self._safe_error(exc, "model import failed"),
                )
                raise
            finally:
                self._imports.pop(import_id, None)
                shutil.rmtree(session.directory, ignore_errors=True)
        if completion_callback is not None and completed_model_id is not None:
            try:
                completion_callback(completed_model_id)
            except Exception:
                # Persisting a UI preference must not invalidate verified artifacts.
                pass

    def _publish_import_locked(self, session: _ImportSession) -> None:
        """Move one validated staged model pair into its final catalog directory."""
        model = self._model(session.model_id)
        staged_main = session.directory / model.model_filename
        staged_draft = session.directory / model.draft_filename
        targets: list[Path] = []
        try:
            if not session.main_part.is_file() or not session.draft_part.is_file():
                raise LocalAIStateError("model import is incomplete")
            os.replace(session.main_part, staged_main)
            os.replace(session.draft_part, staged_draft)
            main = self._validated_model_file(staged_main, "main model")
            draft = self._validated_model_file(staged_draft, "draft model")
            target_dir = self.local_dir / "models" / session.model_id
            target_main = target_dir / model.model_filename
            target_draft = target_dir / model.draft_filename
            if target_main.exists() or target_draft.exists():
                raise LocalAIStateError("model files already exist")
            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(main, target_main)
            targets.append(target_main)
            os.replace(draft, target_draft)
            targets.append(target_draft)
            self._model_paths[session.model_id] = self._validated_model_file(
                target_main, "main model"
            )
            self._draft_paths[session.model_id] = self._validated_model_file(
                target_draft, "draft model"
            )
            if not self._process_is_running() and self._status.state in {
                "not_installed",
                "importing",
                "error",
                "cancelled",
            }:
                self._status = LocalAIStatus(state="installed", model_id=session.model_id)
            self._write_manifest()
        except OSError as exc:
            self._discard_import_targets(session.model_id, targets)
            raise LocalAIStateError("model import is incomplete") from exc
        except Exception:
            self._discard_import_targets(session.model_id, targets)
            raise

    def _discard_import_targets(self, model_id: str, targets: list[Path]) -> None:
        self._model_paths.pop(model_id, None)
        self._draft_paths.pop(model_id, None)
        for target in targets:
            target.unlink(missing_ok=True)

    def delete_model(self, model_id: str) -> bool:
        """Delete an inactive model without exposing a half-deleted inventory."""
        self._model(model_id)
        with self._lock:
            self._reconcile_dead_process_locked()
            running_model_id = (
                self._config[0] if self._process_is_running() and self._config else None
            )
            starting_model_id = self._start_in_flight[0] if self._start_in_flight else None
            if model_id in {running_model_id, starting_model_id}:
                raise LocalAIStateError("cannot delete the active model", code="state_conflict")
            conflicting_jobs = [
                job
                for job in self._jobs.values()
                if getattr(job, "model_id", None) in {None, model_id, "__runtime_update__"}
            ]
            if conflicting_jobs:
                raise LocalAIStateError(
                    "cannot delete a model while another operation that conflicts is in progress",
                    code="state_conflict",
                )
            importing_model_ids = {session.model_id for session in self._imports.values()} | {
                job.session.model_id for job in self._background_import_jobs.values()
            }
            if model_id in importing_model_ids:
                raise LocalAIStateError(
                    "cannot delete a model while it is being imported", code="state_conflict"
                )
            if model_id not in self._model_paths or model_id not in self._draft_paths:
                return False
            main_path = self._deletion_model_path(self._model_paths[model_id], "main model")
            draft_path = self._deletion_model_path(self._draft_paths[model_id], "draft model")
            staging_dir = self.local_dir / ".deleting" / f"{model_id}-{uuid.uuid4().hex}"
            staged_paths: list[tuple[Path, Path]] = []
            try:
                staging_dir.mkdir(parents=True, exist_ok=False)
                for path in (main_path, draft_path):
                    staged = staging_dir / path.name
                    os.replace(path, staged)
                    staged_paths.append((path, staged))
                self._model_paths.pop(model_id)
                self._draft_paths.pop(model_id)
                self._write_manifest()
            except Exception as exc:
                # Keep registry and manifest aligned with the recoverable files
                # if staging or persistence fails. Manifest publication is the
                # commit point; post-commit cleanup must not enter this rollback.
                for original, staged in reversed(staged_paths):
                    if staged.exists() and not original.exists():
                        os.replace(staged, original)
                self._model_paths[model_id] = main_path
                self._draft_paths[model_id] = draft_path
                try:
                    self._write_manifest()
                except OSError:
                    # The original error still carries the failed operation; the
                    # files and in-memory registries remain the safest state.
                    pass
                shutil.rmtree(staging_dir, ignore_errors=True)
                if isinstance(exc, LocalAIStateError):
                    raise
                raise LocalAIStateError("could not delete model files") from exc
            try:
                shutil.rmtree(staging_dir)
            except OSError:
                # The committed manifest is authoritative; an orphaned private
                # staging directory is safe to clean up on a later maintenance pass.
                pass
            return True

    def _deletion_model_path(self, path: Path, label: str) -> Path:
        """Validate deletion targets without requiring a currently valid GGUF payload."""
        candidate = Path(path).expanduser()
        try:
            candidate.resolve(strict=False).relative_to(self.local_dir)
            entry = os.lstat(candidate)
        except (OSError, RuntimeError, ValueError) as exc:
            raise LocalAIStateError(f"{label} is not installed") from exc
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
            raise LocalAIStateError(f"{label} is not installed")
        return candidate.resolve(strict=False)

    def update_runtime(
        self,
        *,
        cpu_fallback: bool = False,
        model_id: str | None = None,
        context_tokens: int | None = None,
        mtp_enabled: bool = False,
        mtp_draft_tokens: int = DEFAULT_MTP_DRAFT_TOKENS,
    ) -> str:
        """Download, verify, and atomically activate the current best runtime.

        The active runtime remains in place until the candidate passes every
        verification gate. Returns a job id so callers can track and cancel.
        """
        with self._lock:
            if self._process_is_running() or self._start_in_flight is not None:
                raise LocalAIStateError(
                    "cannot update runtime while server is active", code="state_conflict"
                )
            if self._imports or self._background_import_jobs:
                raise LocalAIStateError("a model import is already in progress")
            if any(job.cancel_event.is_set() is False for job in self._jobs.values()):
                raise LocalAIStateError("an installation is already in progress")
            installed_models = tuple(
                candidate
                for candidate in MODELS
                if candidate in self._model_paths and candidate in self._draft_paths
            )
            readiness_model_id = model_id if model_id in installed_models else None
            if readiness_model_id is None and installed_models:
                readiness_model_id = installed_models[0]
            if readiness_model_id is not None:
                context_tokens = self._validated_start_options(
                    self._model(readiness_model_id),
                    context_tokens,
                    mtp_enabled,
                    mtp_draft_tokens,
                )
            job_id = uuid.uuid4().hex
            job = _InstallJob(
                job_id,
                "__runtime_update__",
                False,
                threading.Event(),
                cpu_fallback=cpu_fallback,
                context_tokens=context_tokens,
                mtp_enabled=mtp_enabled,
                mtp_draft_tokens=mtp_draft_tokens,
                readiness_model_id=readiness_model_id,
            )
            self._jobs[job_id] = job
            self._operation_status = LocalAIStatus(
                state="downloading",
                model_id="__runtime_update__",
                job_id=job_id,
                operation_kind="runtime_update",
                download_phase="preparing",
            )
            thread = threading.Thread(
                target=self._run_update_runtime_wrapper, args=(job,), daemon=True
            )
            thread.start()
            return job_id

    def delete_runtime(self) -> bool:
        """Delete the installed runtime only when stopped and no model can start with it."""
        with self._lock:
            if self._process_is_running() or self._start_in_flight is not None:
                raise LocalAIStateError("cannot delete runtime while server is running")
            if self._jobs or self._imports or self._background_import_jobs:
                raise LocalAIStateError(
                    "cannot delete runtime while another operation is in progress",
                    code="state_conflict",
                )
            if self._model_paths:
                raise LocalAIStateError("cannot delete runtime while models are installed")
            if self._binary_path is None:
                return False
            binary = self._binary_spec
            self._binary_path = None
            self._binary_spec = None
            self._write_manifest()
            if binary is not None and binary_extract_path is not None:
                extraction_root = binary_extract_path(binary, root=self.local_dir)
                if extraction_root.is_dir():
                    shutil.rmtree(extraction_root, ignore_errors=True)
            if binary is not None and binary_archive_path is not None:
                archive = binary_archive_path(binary, root=self.local_dir)
                archive.unlink(missing_ok=True)
            if binary is not None and binary_companion_archive_path is not None:
                for companion in binary.companions:
                    archive = binary_companion_archive_path(
                        binary, companion.kind, root=self.local_dir
                    )
                    archive.unlink(missing_ok=True)
            return True

    @staticmethod
    def _remove_file_tree(path: Path) -> None:
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except OSError:
            pass

    def _run_install_job_wrapper(self, job: _InstallJob) -> None:
        try:
            self._run_install_job(job)
        except Exception as exc:
            with self._lock:
                if not job.cancel_event.is_set():
                    code = (
                        exc.code
                        if isinstance(exc, LocalAIStateError)
                        else self._classify_install_error(exc)
                    )
                    self._operation_status = LocalAIStatus(
                        state="error",
                        model_id=job.model_id,
                        job_id=job.job_id,
                        operation_kind="model_download",
                        error_code=code,
                        message=self._safe_error(exc, "installation failed"),
                    )
        finally:
            with self._lock:
                self._jobs.pop(job.job_id, None)
                if job.cancel_event.is_set() and self._operation_status is not None:
                    if self._operation_status.job_id == job.job_id:
                        self._operation_status = None
                        if not self._process_is_running():
                            self._status = self._idle_status_locked()

    def _run_update_runtime_wrapper(self, job: _InstallJob) -> None:
        try:
            self._run_update_runtime_job(job)
        except Exception as exc:
            with self._lock:
                if not job.cancel_event.is_set():
                    code = (
                        exc.code
                        if isinstance(exc, LocalAIStateError)
                        else self._classify_install_error(exc)
                    )
                    self._operation_status = LocalAIStatus(
                        state="error",
                        model_id="__runtime_update__",
                        job_id=job.job_id,
                        operation_kind="runtime_update",
                        error_code=code,
                        message=self._safe_error(exc, "runtime update failed"),
                    )
        finally:
            with self._lock:
                self._jobs.pop(job.job_id, None)
                if job.cancel_event.is_set() and self._operation_status is not None:
                    if self._operation_status.job_id == job.job_id:
                        self._operation_status = None
                        if not self._process_is_running():
                            self._status = self._idle_status_locked()

    def _run_install_job(self, job: _InstallJob) -> None:  # noqa: C901
        if any(
            helper is None
            for helper in (
                binary_download_spec,
                model_download_spec,
                draft_download_spec,
                download_catalog_artifact,
                download_verified,
            )
        ):
            raise LocalAIStateError("download support is unavailable")

        # The catalog's pinned release, digest, and archive members are the
        # compatibility contract. Do not exchange a successful model download
        # for an untested arbitrary upstream runtime at first start.
        with self._lock:
            runtime_already_installed = (
                self._binary_path is not None and self._binary_path.is_file()
            )
            current_binary = self._binary_spec
        if current_binary is not None and (
            not runtime_already_installed or getattr(current_binary, "accelerator", "cpu") != "cpu"
        ):
            candidates = (current_binary,)
        else:
            candidates = binary_candidates(detect_hardware_profile())
        with self._lock:
            runtime_is_active = self._process_is_running()
            reassess_runtime = bool(
                runtime_already_installed
                and not runtime_is_active
                and current_binary is not None
                and getattr(current_binary, "accelerator", "cpu") == "cpu"
                and candidates
                and candidates[0].accelerator != "cpu"
            )

        main_spec = model_download_spec(job.model_id, root=self.local_dir)
        draft_spec = self._draft_download_spec(job.model_id)
        # ``transfer_complete`` deliberately accepts an existing final file
        # without another network request. Do not let a broken prior final
        # make every later install retry short-circuit over the same pair.
        self._quarantine_invalid_model_pair(
            job.model_id, main_spec.destination, draft_spec.destination
        )

        previous_runtime = self._runtime_state_snapshot()
        runtime_was_selected = not runtime_already_installed or reassess_runtime
        if runtime_was_selected:
            self._begin_runtime_selection("model_install")
            self._install_best_runtime(
                job,
                candidates,
                preserve_installed=runtime_already_installed,
            )

        # Prove the small runtime is usable before downloading multi-GB model
        # files. A failed runtime must not leave a model that the UI can detect
        # but cannot start.
        for phase, spec in (("main_model", main_spec), ("mtp_drafter", draft_spec)):
            if job.cancel_event.is_set():
                if reassess_runtime:
                    self._restore_runtime_state(previous_runtime)
                raise LocalAIStateError("installation cancelled")
            try:
                self._download_install_artifact(job, phase, spec, False)
            except Exception:
                if reassess_runtime:
                    self._restore_runtime_state(previous_runtime)
                raise
        self._publish_install_progress(job, "finalizing")

        # A completed HTTP transfer is not by itself a usable model. Reject
        # truncated/error payloads before publishing them into manager state.
        try:
            installed_main = self._validated_model_file(Path(main_spec.destination), "main model")
            installed_draft = self._validated_model_file(
                Path(draft_spec.destination), "draft model"
            )
        except LocalAIStateError as exc:
            # A mutable source can leave an invalid final name behind after an
            # interrupted or corrupt transfer. Remove only the catalog-owned
            # final pair so the next retry downloads again instead of looping
            # forever over the same rejected files.
            self._quarantine_model_pair(job.model_id)
            if reassess_runtime:
                self._restore_runtime_state(previous_runtime)
            raise LocalAIStateError(
                "downloaded model artifacts are invalid", code="artifact_invalid"
            ) from exc
        with self._lock:
            self._model_paths[job.model_id] = installed_main
            self._draft_paths[job.model_id] = installed_draft

        if runtime_was_selected:
            self._verify_installed_runtime(
                job,
                candidates,
                previous_runtime=previous_runtime,
            )

        with self._lock:
            if not self._process_is_running() and not (
                self._status.state == "error" and self._status.error_code == "process_exited"
            ):
                self._status = LocalAIStatus(state="installed", model_id=job.model_id)
            self._operation_status = None
            self._write_manifest()
            completion_callback = self._install_completion_callback
            auto_start_callback = self._auto_start_completion_callback
        try:
            if (
                job.start_after_install
                and not runtime_was_selected
                and not job.cancel_event.is_set()
            ):
                self.start(
                    job.model_id,
                    context_tokens=job.context_tokens,
                    mtp_enabled=job.mtp_enabled,
                    mtp_draft_tokens=job.mtp_draft_tokens,
                )
        finally:
            if completion_callback is not None:
                try:
                    completion_callback(job.model_id)
                except Exception:
                    # Application integration cannot invalidate verified artifacts.
                    pass
        if job.start_after_install:
            started_status = self.status()
            if auto_start_callback is not None and started_status.state in {"running", "sleeping"}:
                try:
                    auto_start_callback(started_status)
                except Exception:
                    # Host registration cannot invalidate verified artifacts or the server.
                    pass

    def _runtime_state_snapshot(
        self,
    ) -> tuple[Any, Path | None, RuntimeProbe, str | None, bool, int, bool]:
        with self._lock:
            return (
                self._binary_spec,
                self._binary_path,
                self._runtime_probe,
                self._runtime_device,
                self._runtime_offload_verified,
                self._runtime_offloaded_layers,
                self._cpu_fallback_confirmed,
            )

    def _restore_runtime_state(
        self,
        snapshot: tuple[Any, Path | None, RuntimeProbe, str | None, bool, int, bool],
        *,
        persist_manifest: bool = True,
    ) -> None:
        with self._lock:
            (
                self._binary_spec,
                self._binary_path,
                self._runtime_probe,
                self._runtime_device,
                self._runtime_offload_verified,
                self._runtime_offloaded_layers,
                self._cpu_fallback_confirmed,
            ) = snapshot
            self._write_manifest_if_enabled(persist_manifest)

    @staticmethod
    def _runtime_key(binary: Any) -> tuple[str, str]:
        return (str(binary.profile), str(binary.accelerator))

    def _verify_installed_runtime(
        self,
        job: _InstallJob,
        candidates: tuple[Any, ...],
        *,
        previous_runtime: tuple[Any, Path | None, RuntimeProbe, str | None, bool, int, bool],
    ) -> None:
        """Load the real model before activating a newly selected runtime.

        Device enumeration only identifies a candidate. Accelerator activation
        requires a healthy server plus positive layer-offload evidence at the
        user's unchanged workload. Candidate fallback is restricted to local
        compatibility failures; download and integrity failures remain fatal.
        """
        previous_spec, previous_path, _, _, _, _, _ = previous_runtime
        previous_available = bool(previous_spec is not None and previous_path is not None)
        configured = self._config if self._config and self._config[0] == job.model_id else None
        context_tokens = getattr(job, "context_tokens", None)
        if context_tokens is None:
            context_tokens = configured[1] if configured else DEFAULT_CONTEXT_TOKENS
        mtp_enabled = getattr(job, "mtp_enabled", configured[2] if configured else False)
        mtp_draft_tokens = getattr(
            job,
            "mtp_draft_tokens",
            configured[3] if configured else DEFAULT_MTP_DRAFT_TOKENS,
        )
        attempted: set[tuple[str, str]] = set()
        last_error: LocalAIStateError | None = None

        while not job.cancel_event.is_set():
            selected = self._binary_spec
            if selected is None:
                self._restore_runtime_state(previous_runtime)
                raise LocalAIStateError(
                    "no compatible Integrated AI runtime was found",
                    code="runtime_incompatible",
                )
            selected_key = self._runtime_key(selected)
            try:
                self.start(
                    job.model_id,
                    context_tokens=context_tokens,
                    mtp_enabled=mtp_enabled,
                    mtp_draft_tokens=mtp_draft_tokens,
                    _install_job_id=job.job_id,
                    _persist_manifest=False,
                )
            except LocalAIStateError as exc:
                last_error = exc
                if exc.code == "accelerator_failed" and self._advance_runtime_device():
                    continue
                self._record_runtime_selection(
                    selected,
                    "model_readiness",
                    "rejected",
                    exc.selection_reason or exc.code,
                )
                attempted.add(selected_key)
                if exc.code not in {
                    "accelerator_failed",
                    "runtime_incompatible",
                }:
                    # The staged runtime already passed executable and device
                    # preflight. A port conflict, resource limit, or other
                    # workload/startup failure must remain retryable without
                    # discarding the downloaded runtime or model files.
                    with self._lock:
                        self._write_manifest()
                    raise
                if selected.accelerator == "cpu":
                    self._restore_runtime_state(previous_runtime)
                    raise
                remaining = tuple(
                    candidate
                    for candidate in candidates
                    if self._runtime_key(candidate) not in attempted
                )
                if not remaining:
                    remaining = tuple(
                        candidate
                        for candidate in binary_candidates(detect_hardware_profile())
                        if self._runtime_key(candidate) not in attempted
                    )
                if not remaining:
                    self._restore_runtime_state(previous_runtime)
                    raise
                self._restore_runtime_state(previous_runtime)
                try:
                    self._install_best_runtime(
                        job,
                        remaining,
                        preserve_installed=previous_available,
                    )
                except Exception:
                    self._restore_runtime_state(previous_runtime)
                    raise
                if self._binary_spec is None or self._runtime_key(self._binary_spec) in attempted:
                    self._restore_runtime_state(previous_runtime)
                    raise last_error from None
                if self._binary_spec.accelerator == "cpu" and attempted:
                    self._cpu_fallback_confirmed = True
                continue

            if job.cancel_event.is_set():
                with self._lock:
                    self._stop_spawned_process_locked()
                    self._start_in_flight = None
                    self._status = LocalAIStatus(state="stopped")
                self._restore_runtime_state(previous_runtime, persist_manifest=False)
                raise LocalAIStateError("installation cancelled")
            if not job.start_after_install:
                self.stop()
            self._record_runtime_selection(selected, "model_readiness", "selected")
            return

        self._restore_runtime_state(previous_runtime, persist_manifest=False)
        raise LocalAIStateError("installation cancelled")

    def _install_best_runtime(
        self,
        job: _InstallJob,
        candidates: tuple[Any, ...],
        *,
        preserve_installed: bool,
    ) -> Any:
        """Install the first candidate that proves its advertised capability.

        Download and integrity failures stop the operation. Only a verified
        executable/device incompatibility advances to another already pinned
        backend, so offline or corrupt artifacts can never become a silent CPU
        fallback. Existing installed runtime pointers remain unchanged until a
        candidate passes all gates.
        """
        last_accelerator_error: LocalAIStateError | None = None
        for binary in candidates:
            if job.cancel_event.is_set():
                raise LocalAIStateError("installation cancelled")
            if (
                preserve_installed
                and self._binary_path is not None
                and self._binary_path.is_file()
                and self._binary_spec is not None
                and self._binary_spec.profile == binary.profile
                and self._binary_spec.accelerator == binary.accelerator
            ):
                self._preflight_runtime(binary, self._binary_path)
                self._record_runtime_selection(binary, "device_probe", "accepted")
                if binary.accelerator == "cpu" and last_accelerator_error is not None:
                    self._cpu_fallback_confirmed = True
                return binary
            binary_spec = binary_download_spec(binary, root=self.local_dir)
            companion_specs = (
                tuple(
                    binary_companion_download_spec(binary, companion.kind, root=self.local_dir)
                    for companion in binary.companions
                )
                if binary_companion_download_spec is not None
                else ()
            )
            for spec in (binary_spec, *companion_specs):
                self._download_install_artifact(job, "runtime", spec, True)
            try:
                self._install_downloaded_runtime(binary, binary_spec, companion_specs)
                self._record_runtime_selection(binary, "device_probe", "accepted")
                if binary.accelerator == "cpu" and last_accelerator_error is not None:
                    self._cpu_fallback_confirmed = True
                return binary
            except LocalAIStateError as exc:
                self._record_runtime_selection(
                    binary, "runtime_preflight", "rejected", exc.selection_reason or exc.code
                )
                if binary.accelerator == "cpu" or exc.code not in {
                    "accelerator_failed",
                    "runtime_incompatible",
                }:
                    raise
                last_accelerator_error = exc
        if preserve_installed and self._binary_path is not None and self._binary_spec is not None:
            self._preflight_runtime(self._binary_spec, self._binary_path)
            self._record_runtime_selection(self._binary_spec, "device_probe", "accepted")
            return self._binary_spec
        raise last_accelerator_error or LocalAIStateError(
            "no compatible Integrated AI runtime was found", code="runtime_incompatible"
        )

    def _quarantine_model_pair(self, model_id: str) -> None:
        model = self._model(model_id)
        directory = self.local_dir / "models" / model_id
        for filename in (model.model_filename, model.draft_filename):
            self._remove_file_tree(directory / filename)
        with self._lock:
            self._model_paths.pop(model_id, None)
            self._draft_paths.pop(model_id, None)

    def _quarantine_invalid_model_pair(
        self, model_id: str, main_path: Path, draft_path: Path
    ) -> None:
        """Remove only a catalog pair that cannot pass the local GGUF gate."""
        candidates = (Path(main_path), Path(draft_path))
        if not any(candidate.exists() or candidate.is_symlink() for candidate in candidates):
            return
        try:
            self._validated_model_file(candidates[0], "main model")
            self._validated_model_file(candidates[1], "draft model")
        except LocalAIStateError:
            self._quarantine_model_pair(model_id)

    def _install_downloaded_runtime(
        self, binary: Any, binary_spec: Any, companion_specs: tuple[Any, ...]
    ) -> None:
        if extract_verified_archive is None:
            raise LocalAIStateError("archive extraction support is unavailable")
        extraction_root = self._runtime_extraction_root(binary)
        extracted = self._existing_runtime_server(extraction_root)
        if extracted is None:
            extracted = extract_verified_archive(
                Path(binary_spec.destination),
                extraction_root,
                expected_sha256=binary_spec.expected_sha256,
                expected_bytes=binary_spec.expected_bytes,
                allowed_members=binary.archive_members,
            )
        self._install_runtime_companions(binary, companion_specs, Path(extracted).parent)
        self._preflight_runtime(binary, Path(extracted))
        with self._lock:
            self._binary_spec = binary
            self._binary_path = Path(extracted)

    def _preflight_runtime(self, binary: Any, server: Path) -> RuntimeProbe:
        """Prove a staged runtime executes and supports AQA's command contract."""
        candidate = Path(server)
        try:
            entry = os.lstat(candidate)
        except OSError as exc:
            raise LocalAIStateError(
                "Integrated AI runtime is not available", code="runtime_incompatible"
            ) from exc
        if (
            stat.S_ISLNK(entry.st_mode)
            or not stat.S_ISREG(entry.st_mode)
            or candidate.name != binary.engine_name
            or (os.name != "nt" and not os.access(candidate, os.X_OK))
        ):
            raise LocalAIStateError(
                "Integrated AI runtime is not compatible", code="runtime_incompatible"
            )
        try:
            completed = subprocess.run(
                [str(candidate), "--help"],
                cwd=str(candidate.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=RUNTIME_PREFLIGHT_TIMEOUT,
                check=False,
                shell=False,
                **({"creationflags": hidden_console_flags()} if os.name == "nt" else {}),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            reason = (
                "probe_timeout"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "missing_runtime_library"
                if getattr(exc, "winerror", None) == 126
                else "runtime_launch_failed"
            )
            raise LocalAIStateError(
                "Integrated AI runtime is not compatible",
                code="runtime_incompatible",
                selection_reason=reason,
            ) from exc
        output = completed.stdout if isinstance(completed.stdout, str) else ""
        missing_flags = [
            flag
            for flag in _REQUIRED_RUNTIME_FLAGS
            if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(flag)}(?![A-Za-z0-9_-])", output) is None
        ]
        if completed.returncode != 0 or missing_flags:
            reason = (
                "missing_runtime_library"
                if completed.returncode & 0xFFFFFFFF == 0xC0000135
                else "runtime_options_unavailable"
                if missing_flags
                else "runtime_launch_failed"
            )
            raise LocalAIStateError(
                "Integrated AI runtime does not support the required server options",
                code="runtime_incompatible",
                selection_reason=reason,
            )
        probe = self._probe_runtime_devices(candidate)
        if binary.accelerator != "cpu" and probe.state != "gpu_candidate":
            raise LocalAIStateError(
                "Integrated AI accelerator could not be verified",
                code="accelerator_failed",
                selection_reason=probe.reason or "probe_failed",
            )
        self._runtime_probe = probe
        self._runtime_device = probe.devices[0].identifier if probe.devices else None
        self._runtime_offload_verified = False
        self._runtime_offloaded_layers = 0
        return probe

    def _runtime_device_for_start(self, binary_path: Path) -> str:
        """Return the exact probed device id, or explicit CPU-only selection."""
        accelerated = bool(
            self._binary_spec and getattr(self._binary_spec, "accelerator", "cpu") != "cpu"
        )
        if not accelerated:
            return "none"
        if self._runtime_probe.state != "gpu_candidate" or not self._runtime_probe.devices:
            probe = self._probe_runtime_devices(binary_path)
            if probe.state != "gpu_candidate" or not probe.devices:
                raise LocalAIStateError(
                    "Integrated AI accelerator could not be verified",
                    code="accelerator_failed",
                )
            self._runtime_probe = probe
        identifiers = tuple(device.identifier for device in self._runtime_probe.devices)
        if self._runtime_device not in identifiers:
            self._runtime_device = identifiers[0]
        return self._runtime_device

    def _advance_runtime_device(self) -> bool:
        """Advance once through the exact runtime's bounded enumerated devices."""
        identifiers = tuple(device.identifier for device in self._runtime_probe.devices)
        try:
            current_index = identifiers.index(self._runtime_device)
        except ValueError:
            current_index = -1
        next_index = current_index + 1
        if next_index >= len(identifiers):
            return False
        self._runtime_device = identifiers[next_index]
        return True

    def _verify_current_runtime_readiness(self, job: _InstallJob, model_id: str) -> None:
        """Run one staged runtime against a real installed model and stop it."""
        while not job.cancel_event.is_set():
            try:
                self.start(
                    model_id,
                    context_tokens=job.context_tokens,
                    mtp_enabled=job.mtp_enabled,
                    mtp_draft_tokens=job.mtp_draft_tokens,
                    _install_job_id=job.job_id,
                    _persist_manifest=False,
                )
            except LocalAIStateError as exc:
                if exc.code == "accelerator_failed" and self._advance_runtime_device():
                    continue
                raise
            with self._lock:
                self._stop_spawned_process_locked()
                self._start_in_flight = None
                self._status = LocalAIStatus(state="stopped")
            return
        raise LocalAIStateError("runtime update cancelled")

    @staticmethod
    def _probe_runtime_devices(server: Path) -> RuntimeProbe:
        """Enumerate devices with the exact staged executable, never a CPU proxy."""
        try:
            completed = subprocess.run(
                [str(server), "--list-devices"],
                cwd=str(server.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=RUNTIME_DEVICE_PROBE_TIMEOUT,
                check=False,
                shell=False,
                **({"creationflags": hidden_console_flags()} if os.name == "nt" else {}),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            reason = (
                "probe_timeout"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "missing_runtime_library"
                if getattr(exc, "winerror", None) == 126
                else "probe_failed"
            )
            return RuntimeProbe("failed", reason=reason)
        output = completed.stdout if isinstance(completed.stdout, str) else ""
        if completed.returncode & 0xFFFFFFFF == 0xC0000135:
            return RuntimeProbe("failed", reason="missing_runtime_library")
        return parse_runtime_devices(output, returncode=completed.returncode)

    def _runtime_extraction_root(self, binary: Any) -> Path:
        if binary_extract_path is not None:
            return binary_extract_path(binary, root=self.local_dir)
        return self.local_dir / "llama.cpp" / binary.release_tag / binary.platform / "extracted"

    @staticmethod
    def _existing_runtime_server(extraction_root: Path) -> Path | None:
        server_name = (
            "llama-server.exe" if platform.system().lower().startswith("win") else "llama-server"
        )
        candidates = [extraction_root / server_name]
        if extraction_root.is_dir():
            candidates.extend(
                child / server_name for child in extraction_root.iterdir() if child.is_dir()
            )
        return next((candidate for candidate in candidates if candidate.exists()), None)

    def _download_install_artifact(
        self, job: _InstallJob, phase: str, spec: Any, is_runtime: bool
    ) -> None:
        self._publish_install_progress(job, phase)

        def progress(downloaded: int, expected: int) -> None:
            self._publish_install_progress(job, phase, downloaded, expected)

        if is_runtime:
            download_verified(
                url=spec.url,
                destination=spec.destination,
                expected_sha256=spec.expected_sha256,
                expected_bytes=spec.expected_bytes,
                progress_callback=progress,
                cancel_event=job.cancel_event,
            )
            return
        download_catalog_artifact(
            spec,
            progress_callback=progress,
            cancel_event=job.cancel_event,
        )

    def _publish_install_progress(
        self, job: _InstallJob, phase: str, downloaded: int = 0, expected: int = 0
    ) -> None:
        safe_downloaded = max(0, int(downloaded)) if isinstance(downloaded, (int, float)) else 0
        safe_expected = max(0, int(expected)) if isinstance(expected, (int, float)) else 0
        with self._lock:
            self._operation_status = LocalAIStatus(
                state="downloading",
                model_id=job.model_id,
                job_id=job.job_id,
                operation_kind="model_download",
                downloaded_bytes=safe_downloaded,
                total_bytes=safe_expected,
                available_disk_bytes=self._available_disk_bytes(),
                download_phase=phase,
            )

    def _available_disk_bytes(self) -> int | None:
        try:
            available = shutil.disk_usage(self.local_dir).free
        except OSError:
            return None
        return available if isinstance(available, int) and available >= 0 else None

    def _run_update_runtime_job(self, job: _InstallJob) -> None:  # noqa: C901
        if any(
            helper is None
            for helper in (binary_download_spec, download_verified, extract_verified_archive)
        ):
            raise LocalAIStateError("download support is unavailable")
        if self._process_is_running():
            raise LocalAIStateError("cannot update runtime while server is running")
        previous_runtime = self._runtime_state_snapshot()
        self._begin_runtime_selection("runtime_update")
        last_compatibility_error: LocalAIStateError | None = None
        for binary in self._runtime_update_candidates(job):
            try:
                self._install_runtime_update_candidate(job, binary, previous_runtime)
            except LocalAIStateError as exc:
                self._record_runtime_selection(
                    binary, "runtime_update", "rejected", exc.selection_reason or exc.code
                )
                if getattr(binary, "accelerator", "cpu") == "cpu" or exc.code not in {
                    "accelerator_failed",
                    "runtime_incompatible",
                }:
                    raise
                last_compatibility_error = exc
                continue
            with self._lock:
                if (
                    last_compatibility_error is not None
                    and getattr(binary, "accelerator", "cpu") == "cpu"
                ):
                    self._cpu_fallback_confirmed = True
                    try:
                        self._write_manifest()
                    except OSError:
                        # The runtime is already committed; capability persistence is secondary.
                        pass
                self._operation_status = None
                self._status = self._idle_status_locked()
            self._record_runtime_selection(binary, "runtime_update", "selected")
            return
        raise last_compatibility_error or LocalAIStateError(
            "no compatible Integrated AI runtime was found", code="runtime_incompatible"
        )

    def _install_runtime_update_candidate(  # noqa: C901
        self,
        job: _InstallJob,
        binary: Any,
        previous_runtime: tuple[Any, Path | None, RuntimeProbe, str | None, bool, int, bool],
    ) -> None:
        binary_spec = binary_download_spec(binary, root=self.local_dir)
        companion_specs = (
            tuple(
                binary_companion_download_spec(binary, companion.kind, root=self.local_dir)
                for companion in binary.companions
            )
            if binary_companion_download_spec is not None
            else ()
        )
        runtime_specs = (binary_spec, *companion_specs)

        self._download_runtime_update_artifacts(job, runtime_specs)

        with self._lock:
            self._operation_status = LocalAIStatus(
                state="downloading",
                model_id="__runtime_update__",
                job_id=job.job_id,
                operation_kind="runtime_update",
                download_phase="finalizing",
            )

        archive = Path(binary_spec.destination)
        extraction_root = (
            binary_extract_path(binary, root=self.local_dir)
            if binary_extract_path is not None
            else self.local_dir / "llama.cpp" / binary.release_tag / binary.platform / "extracted"
        )
        # Extract to a unique candidate directory alongside the canonical one.
        # Nothing published in the manifest points at this staging path.
        candidate_root = extraction_root.with_name(
            extraction_root.name + f"-update-{uuid.uuid4().hex}"
        )
        if candidate_root.exists():
            shutil.rmtree(candidate_root, ignore_errors=True)
        candidate_server = extract_verified_archive(
            archive,
            candidate_root,
            expected_sha256=binary_spec.expected_sha256,
            expected_bytes=binary_spec.expected_bytes,
            allowed_members=binary.archive_members,
        )
        if not candidate_server.is_file():
            shutil.rmtree(candidate_root, ignore_errors=True)
            raise LocalAIStateError("updated runtime verification failed")
        try:
            self._install_runtime_companions(binary, companion_specs, candidate_server.parent)
            self._preflight_runtime(binary, candidate_server)
            if job.cancel_event.is_set():
                raise LocalAIStateError("runtime update cancelled")
            readiness_model_id = getattr(job, "readiness_model_id", None)
            if readiness_model_id is not None:
                with self._lock:
                    self._binary_spec = binary
                    self._binary_path = candidate_server
                self._verify_current_runtime_readiness(job, readiness_model_id)
                candidate_runtime = self._runtime_state_snapshot()
                self._restore_runtime_state(previous_runtime)
            else:
                candidate_runtime = (
                    binary,
                    candidate_server,
                    self._runtime_probe,
                    self._runtime_device,
                    False,
                    0,
                    self._cpu_fallback_confirmed,
                )
        except Exception:
            self._restore_runtime_state(previous_runtime)
            shutil.rmtree(candidate_root, ignore_errors=True)
            raise

        try:
            relative_server = candidate_server.relative_to(candidate_root)
        except ValueError as exc:
            shutil.rmtree(candidate_root, ignore_errors=True)
            raise LocalAIStateError("updated runtime verification failed") from exc

        backup_root = extraction_root.with_name(
            extraction_root.name + f"-backup-{uuid.uuid4().hex}"
        )
        previous_spec, previous_path, _, _, _, _, _ = previous_runtime
        moved_active = False
        try:
            if job.cancel_event.is_set():
                raise LocalAIStateError("runtime update cancelled")
            extraction_root.parent.mkdir(parents=True, exist_ok=True)
            if extraction_root.exists():
                os.replace(extraction_root, backup_root)
                moved_active = True
            os.replace(candidate_root, extraction_root)
            final_server = (extraction_root / relative_server).resolve()
            if not final_server.is_file():
                raise LocalAIStateError("updated runtime verification failed")
            with self._lock:
                self._binary_spec = binary
                self._binary_path = final_server
                self._runtime_probe = candidate_runtime[2]
                self._runtime_device = candidate_runtime[3]
                self._runtime_offload_verified = candidate_runtime[4]
                self._runtime_offloaded_layers = candidate_runtime[5]
                self._cpu_fallback_confirmed = candidate_runtime[6]
                self._write_manifest()
        except Exception:
            with self._lock:
                self._binary_spec = previous_spec
                self._binary_path = previous_path
            if extraction_root.exists():
                shutil.rmtree(extraction_root, ignore_errors=True)
            if moved_active and backup_root.exists():
                os.replace(backup_root, extraction_root)
            # Restore the published manifest if writing the candidate failed.
            if previous_spec is not None and previous_path is not None:
                self._write_manifest()
            raise
        finally:
            if candidate_root.exists():
                shutil.rmtree(candidate_root, ignore_errors=True)
        if backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)

    def _download_runtime_update_artifacts(
        self, job: _InstallJob, runtime_specs: tuple[Any, ...]
    ) -> None:
        for spec in runtime_specs:
            self._publish_runtime_update_progress(job)
            download_verified(
                url=spec.url,
                destination=spec.destination,
                expected_sha256=spec.expected_sha256,
                expected_bytes=spec.expected_bytes,
                progress_callback=lambda downloaded, expected: (
                    self._publish_runtime_update_progress(job, downloaded, expected)
                ),
                cancel_event=job.cancel_event,
            )
        if job.cancel_event.is_set():
            raise LocalAIStateError("runtime update cancelled")

    def _publish_runtime_update_progress(
        self, job: _InstallJob, downloaded: int = 0, expected: int = 0
    ) -> None:
        safe_downloaded = max(0, int(downloaded)) if isinstance(downloaded, (int, float)) else 0
        safe_expected = max(0, int(expected)) if isinstance(expected, (int, float)) else 0
        with self._lock:
            self._operation_status = LocalAIStatus(
                state="downloading",
                model_id="__runtime_update__",
                job_id=job.job_id,
                operation_kind="runtime_update",
                downloaded_bytes=safe_downloaded,
                total_bytes=safe_expected,
                download_phase="runtime",
            )

    def _runtime_update_binary(self, job: _InstallJob) -> Any:
        return self._runtime_update_candidates(job)[0]

    def _runtime_update_candidates(self, job: _InstallJob) -> tuple[Any, ...]:
        detected = binary_candidates(detect_hardware_profile())
        current = self._binary_spec
        ordered = (
            (current, *detected)
            if current is not None and getattr(current, "accelerator", "cpu") != "cpu"
            else detected
        )
        unique_by_key: dict[tuple[str, str], Any] = {}
        for binary in ordered:
            unique_by_key.setdefault(self._runtime_key(binary), binary)
        unique = tuple(unique_by_key.values())
        if not unique:
            raise LocalAIStateError(
                "no compatible Integrated AI runtime was found", code="runtime_incompatible"
            )
        if not getattr(job, "cpu_fallback", False):
            return unique
        cpu = tuple(binary for binary in unique if getattr(binary, "accelerator", "cpu") == "cpu")
        if cpu:
            return cpu
        binary = unique[0]
        try:
            return (binary_for_profile(f"{binary.platform}-cpu"),)
        except ValueError:
            # Apple Silicon's Metal build includes a CPU execution mode;
            # preserve the same verified archive but disable acceleration.
            return (replace(binary, accelerator="cpu", runtime=None),)

    @staticmethod
    def _install_runtime_companions(
        binary: Any, companion_specs: tuple[Any, ...], destination: Path
    ) -> None:
        companions = binary.companions
        if not companions:
            return
        if (
            install_verified_companion_archive is None
            or bundled_third_party_license_path is None
            or len(companions) != len(companion_specs)
        ):
            raise LocalAIStateError("runtime companion support is unavailable")
        for companion, spec in zip(companions, companion_specs, strict=True):
            license_source = bundled_third_party_license_path(companion.license_filename)
            installed = install_verified_companion_archive(
                Path(spec.destination),
                destination,
                expected_sha256=spec.expected_sha256,
                expected_bytes=spec.expected_bytes,
                allowed_members=companion.archive_members,
                license_source=license_source,
                license_sha256=companion.license_sha256,
                license_bytes=companion.license_bytes,
                installed_license_filename=companion.installed_license_filename,
            )
            if len(installed) != len(companion.archive_members):
                raise LocalAIStateError("runtime companion installation failed")

    def _draft_download_spec(self, model_id: str) -> Any:
        if draft_download_spec is None:
            raise LocalAIStateError("draft download specification is unavailable")
        return draft_download_spec(model_id, root=self.local_dir)

    def _model(self, model_id: str) -> Any:
        try:
            return MODELS[model_id]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unknown catalog model: {model_id!r}") from exc

    def _model_path(self, model_id: str, *, draft: bool) -> Path:
        """Return the on-disk path of a verified, final model/draft file.

        The on-disk check uses :meth:`_validated_model_file`, so a
        ``.part`` streaming placeholder, a zero-byte file, a symlink, or
        any path outside ``local_dir`` is treated as not installed.  A
        bare ``.part`` must never satisfy this lookup; only the
        atomically-published final filename counts. Delegates to
        :meth:`_cached_or_discovered_model_path` so the cache and the
        cached and catalog-path discovery share a single validation gate.
        """
        validated = self._cached_or_discovered_model_path(model_id, draft=draft)
        if validated is None:
            label = "draft model" if draft else "main model"
            raise LocalAIStateError(f"{label} is not installed")
        return validated

    def _resolve_binary_path(self) -> Path:
        if self._runtime_available_locked():
            assert self._binary_path is not None
            return self._binary_path
        binary = self._binary_spec or select_binary(detect_hardware_profile())
        self._binary_spec = binary
        server_name = (
            "llama-server.exe" if platform.system().lower().startswith("win") else "llama-server"
        )
        candidate_root = (
            binary_extract_path(binary, root=self.local_dir)
            if binary_extract_path is not None
            else self.local_dir
            / "llama.cpp"
            / binary.release_tag
            / binary.platform
            / "backends"
            / binary.profile
            / "extracted"
        )
        candidates = [candidate_root / server_name]
        candidates.extend(
            candidate_root / member
            for member in binary.archive_members
            if Path(member).name == server_name
        )
        for candidate in candidates:
            if candidate.is_file():
                resolved = candidate.resolve()
                if self._has_required_runtime_companions(binary, resolved.parent):
                    self._binary_spec = binary
                    self._binary_path = resolved
                    return resolved
        if candidate_root.is_dir():
            for child in candidate_root.iterdir():
                if child.is_dir():
                    server_candidate = child / server_name
                    if server_candidate.is_file():
                        resolved = server_candidate.resolve()
                        if self._has_required_runtime_companions(binary, resolved.parent):
                            self._binary_spec = binary
                            self._binary_path = resolved
                            return resolved
        raise LocalAIStateError(
            "Integrated AI runtime is not installed", code="runtime_incompatible"
        )

    def _validate_artifacts(self, model_id: str, binary: Path, model: Path, draft: Path) -> None:
        if not binary.is_file():
            raise LocalAIStateError(
                "verified llama-server is not installed", code="artifact_invalid"
            )
        self._validated_model_file(model, "main model")
        self._validated_model_file(draft, "draft model")
        if os.name != "nt" and not os.access(binary, os.X_OK):
            raise LocalAIStateError(
                "Integrated AI runtime is not executable", code="runtime_incompatible"
            )

    def _validated_model_file(
        self,
        path: Path,
        label: str,
        *,
        require_root_containment: bool = True,
    ) -> Path:
        """Confirm a model/draft path is a final, non-empty, root-contained regular file.

        Catalog downloads reach this helper only after exact size and SHA-256
        verification and atomic publication. Imported or previously installed
        artifacts remain supported, so this restore-time gate deliberately:

        * uses ``os.lstat`` to reject symlinks (the OS symlink target is not
          a verified install);
        * rejects the ``.part`` filename that the downloader writes while
          streaming;
        * requires a positive ``st_size`` so a zero-byte placeholder cannot
          be treated as installed;
        * confirms ``local_dir`` containment for externally-supplied paths
          (manifest load, on-disk discovery) so a tampered manifest cannot
          cause a file outside the Local AI root to be loaded as a model.

        Raises :class:`LocalAIStateError` with a safe ``label``-prefixed
        message; returns the resolved absolute path on success.
        """
        candidate = Path(path).expanduser()
        self._validate_model_candidate(candidate, label)
        resolved = self._resolve_model_candidate(candidate, label)
        if require_root_containment:
            self._validate_model_root_containment(resolved, label)
        return resolved

    @staticmethod
    def _validate_model_candidate(candidate: Path, label: str) -> None:
        if candidate.name.endswith(".part"):
            raise LocalAIStateError(f"{label} is not installed")
        try:
            entry = os.lstat(candidate)
        except OSError as exc:
            raise LocalAIStateError(f"{label} is not installed") from exc
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode) or entry.st_size < 8:
            raise LocalAIStateError(f"{label} is not installed")
        try:
            with candidate.open("rb") as stream:
                if stream.read(4) != b"GGUF":
                    raise LocalAIStateError(f"{label} is not installed")
        except OSError as exc:
            raise LocalAIStateError(f"{label} is not installed") from exc

    @staticmethod
    def _resolve_model_candidate(candidate: Path, label: str) -> Path:
        try:
            return candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise LocalAIStateError(f"{label} is not installed") from exc

    def _validate_model_root_containment(self, resolved: Path, label: str) -> None:
        try:
            resolved.relative_to(self.local_dir)
        except ValueError as exc:
            raise LocalAIStateError(f"{label} is not installed") from exc

    @staticmethod
    def _verify_file(path: Path, expected_bytes: int, expected_sha256: str, label: str) -> None:
        if not path.is_file():
            raise LocalAIStateError(f"verified {label} is not installed")
        if path.stat().st_size != expected_bytes:
            raise LocalAIStateError(f"{label} integrity check failed")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise LocalAIStateError(f"{label} integrity check failed")

    def _reserve_loopback_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if platform.system().lower().startswith("win"):
                exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
                if exclusive is not None:
                    sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((LOCAL_HOST, self._configured_port))
            except OSError as exc:
                if self._configured_port == 0:
                    raise LocalAIStateError(
                        "loopback port is unavailable", code="port_conflict"
                    ) from exc
                try:
                    sock.bind((LOCAL_HOST, 0))
                except OSError as fallback_exc:
                    raise LocalAIStateError(
                        "loopback port is unavailable", code="port_conflict"
                    ) from fallback_exc
            return int(sock.getsockname()[1])

    def _accelerator_value(self) -> bool:
        if self._accelerator_available is not None:
            return bool(self._accelerator_available)
        return bool(self._binary_spec and getattr(self._binary_spec, "accelerator", "cpu") != "cpu")

    @staticmethod
    def _build_command(
        *,
        binary_path: Path,
        model: Any,
        model_path: Path,
        draft_path: Path,
        context_tokens: int,
        mtp_enabled: bool,
        mtp_draft_tokens: int,
        accelerator_available: bool,
        runtime_device: str,
        port: int,
    ) -> list[str]:
        command = [
            str(binary_path),
            "--model",
            str(model_path),
        ]
        if mtp_enabled:
            command.extend(
                [
                    "--model-draft",
                    str(draft_path),
                    "--spec-type",
                    "draft-mtp",
                    "--spec-draft-n-max",
                    str(mtp_draft_tokens),
                ]
            )
        command.extend(
            [
                "--alias",
                model.api_alias,
                "--flash-attn",
                model.flash_attention,
                "--ctx-size",
                str(context_tokens),
                "--temp",
                "1.0",
                "--top-p",
                "0.95",
                "--top-k",
                "64",
                "--device",
                runtime_device,
                "--n-gpu-layers",
                "auto" if accelerator_available else "0",
                "--fit",
                "on",
                "--verbosity",
                "4" if accelerator_available else "3",
                "--sleep-idle-seconds",
                str(IDLE_SLEEP_SECONDS),
                "--host",
                LOCAL_HOST,
                "--port",
                str(port),
            ]
        )
        return command

    def _spawn(self, command: list[str]) -> Any:
        kwargs: dict[str, Any] = {
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = hidden_console_flags(process_group=True)
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(command, **kwargs)

    def _poll_health(self, port: int) -> str:
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            with self._lock:
                process = self._process
                start_in_flight = self._start_in_flight
            if process is None or start_in_flight is None:
                raise LocalAIStateError(
                    "Integrated AI startup was interrupted", code="state_conflict"
                )
            if process.poll() is not None:
                # Reader threads deliberately do not acquire the lifecycle
                # lock, so give an immediately-exited process one scheduler
                # turn to drain its final diagnostic line before cleanup.
                time.sleep(0.001)
                raise LocalAIStateError(
                    "Integrated AI service exited during startup",
                    code=self._process_exit_code(),
                )
            try:
                health = requests.get(f"http://{LOCAL_HOST}:{port}/health", timeout=0.5)
                if health.status_code == 200:
                    response = requests.get(f"http://{LOCAL_HOST}:{port}/v1/models", timeout=0.5)
                    if response.status_code == 200:
                        payload = response.json()
                        model_id = self._extract_model_id(payload)
                        if model_id:
                            return model_id
            except (requests.RequestException, ValueError, TypeError, KeyError):
                pass
            if self._health_interval:
                time.sleep(self._health_interval)
        raise LocalAIStateError(
            "Integrated AI service did not become ready", code="startup_timeout"
        )

    @staticmethod
    def _extract_model_id(payload: Any) -> str | None:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None
        value = data[0].get("id")
        if not isinstance(value, str):
            return None
        value = " ".join(value.split())
        # Some llama.cpp builds return the model file path as the id. Extract
        # only the filename so managed paths never reach the browser.
        if "/" in value or "\\" in value:
            from pathlib import PurePosixPath, PureWindowsPath

            path = PureWindowsPath(value) if "\\" in value else PurePosixPath(value)
            value = path.name
            if not value:
                return None
        if "/" in value or "\\" in value or "--" in value:
            return None
        return value[:200] or None

    def _read_server_model_id(self, _port: int) -> str | None:
        return None

    def _start_log_reader(self, process: Any) -> None:
        def read(stream: Any) -> None:
            try:
                for line in iter(stream.readline, ""):
                    text = " ".join(str(line).split())
                    if text:
                        # ``deque.append`` is atomic in CPython. Keeping it
                        # outside the lifecycle lock prevents a verbose child
                        # from blocking startup or losing its exit evidence.
                        self._log_lines.append(text[:500])
            except (OSError, ValueError):
                return

        for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
            if stream is not None and hasattr(stream, "readline"):
                threading.Thread(target=read, args=(stream,), daemon=True).start()

    def _write_owner_marker(self, executable: Path, port: int) -> None:
        now = time.time()
        marker = {
            "parent_pid": os.getpid(),
            "child_pid": int(self._owner_pid),
            "executable": str(executable.resolve()),
            "port": int(port),
            "timestamp": now,
            "started_at": now,
        }
        creation_time = self._windows_process_creation_time(int(self._owner_pid))
        if creation_time is not None:
            marker["process_creation_time"] = creation_time
        elif not self._windows_host():
            start_token = self._posix_process_start_token(int(self._owner_pid))
            if start_token is None:
                raise OSError("process identity unavailable")
            marker["process_start_token"] = start_token
        temporary = self._owner_marker_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(marker), encoding="utf-8")
        os.replace(temporary, self._owner_marker_path)

    def _process_is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _owned_process_matches(self) -> bool:
        if self._process is None or self._owner_pid is None or self._process_command is None:
            return False
        if int(getattr(self._process, "pid", -1)) != self._owner_pid:
            return False
        try:
            marker = json.loads(self._owner_marker_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        executable = str(Path(self._process_command[0]).resolve())
        return (
            marker.get("parent_pid") == os.getpid()
            and marker.get("child_pid") == self._owner_pid
            and marker.get("executable") == executable
            and marker.get("port") == self._port
        )

    @staticmethod
    def _classify_startup_error(exc: Exception) -> str:
        if isinstance(exc, PermissionError):
            return "permission_denied"
        if isinstance(exc, FileNotFoundError):
            return "accelerator_failed"
        text = " ".join(str(exc).split()).lower()
        if "port" in text or "address already" in text:
            return "port_conflict"
        if "memory" in text or "alloc" in text:
            return "insufficient_resources"
        if "permission" in text or "denied" in text:
            return "permission_denied"
        if "library" in text or "unsupported" in text or "executable" in text:
            return "runtime_incompatible"
        return "startup_failed"

    def _process_exit_code(self) -> str:
        """Classify only unambiguous model-load failures from bounded child output."""
        output = " ".join(self._log_lines)
        if re.search(
            r"(?:failed to load|invalid|corrupt)\s+(?:the\s+)?(?:gguf|model)\b"
            r"|\b(?:gguf|model)\b.{0,80}\b(?:failed to load|invalid|corrupt)\b",
            output,
            re.IGNORECASE,
        ):
            return "artifact_invalid"
        if re.search(r"out of memory|cannot allocate|allocation failed|\boom\b", output, re.I):
            return "insufficient_resources"
        if re.search(
            r"address already in use|failed to (?:bind|listen)|bind\(\).{0,40}failed",
            output,
            re.I,
        ):
            return "port_conflict"
        if re.search(
            r"(?:cuda|hip|rocm|metal|vulkan|sycl|level.zero).{0,80}(?:driver|device|loader|library|error)",
            output,
            re.I,
        ):
            return "accelerator_failed"
        return "process_exited"

    @staticmethod
    def _classify_install_error(exc: Exception) -> str:
        text = " ".join(str(exc).split()).lower()
        if "free space" in text or "storage" in text:
            return "insufficient_disk_space"
        if "cancel" in text:
            return "installation_cancelled"
        if "artifact" in text or "integrity" in text:
            return "artifact_invalid"
        if "permission" in text or "denied" in text:
            return "permission_denied"
        return "download_failed"

    def _clear_owned_process_locked(self, *, remove_marker: bool) -> None:
        self._process = None
        self._process_command = None
        self._owner_pid = None
        self._config = None
        self._port = None
        self._server_model_name = None
        self._active_requests = 0
        self._last_request_idle_at = None
        if remove_marker:
            try:
                self._owner_marker_path.unlink()
            except FileNotFoundError:
                pass

    def _stop_spawned_process_locked(self) -> None:
        """Stop the just-spawned child even if marker publication never completed."""
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except (subprocess.TimeoutExpired, TimeoutError):
                    self._force_kill(process)
                    process.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            self._clear_owned_process_locked(remove_marker=True)

    def _stop_locked(self) -> bool:
        process = self._process
        if process is None or not self._owned_process_matches():
            return False
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except (subprocess.TimeoutExpired, TimeoutError):
                    self._force_kill(process)
                    process.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError):
            return False
        if process.poll() is None:
            return False
        self._clear_owned_process_locked(remove_marker=True)
        self._start_in_flight = None
        self._status = LocalAIStatus(state="stopped")
        self._write_manifest()
        return True

    @staticmethod
    def _force_kill(process: Any) -> None:
        if os.name == "nt":
            process.kill()
            return
        try:
            os.killpg(os.getpgid(int(process.pid)), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()

    def _reconcile_owner_marker(self) -> None:
        if not self._owner_marker_path.exists():
            return
        try:
            marker = json.loads(self._owner_marker_path.read_text(encoding="utf-8"))
            pid = int(marker["child_pid"])
            port = int(marker["port"])
            executable = str(Path(marker["executable"]).resolve())
            creation_time = int(marker["process_creation_time"]) if self._windows_host() else None
        except (OSError, ValueError, TypeError, KeyError):
            self._owner_marker_path.unlink(missing_ok=True)
            return
        if not self._pid_alive(pid):
            self._owner_marker_path.unlink(missing_ok=True)
            return
        if not self._pid_matches_marker(pid, executable, port):
            raise LocalAIStateError("another process owns the configured Local AI server")
        try:
            if self._windows_host():
                self._terminate_verified_windows_process(pid, executable, creation_time)
            else:
                self._terminate_stale_posix_process(pid)
        except OSError as exc:
            raise LocalAIStateError("stale owned server could not be stopped") from exc
        self._owner_marker_path.unlink(missing_ok=True)

    def _terminate_stale_posix_process(self, pid: int) -> None:
        """Stop a verified stale child, escalating only after a bounded wait."""
        os.kill(pid, signal.SIGTERM)
        if self._wait_for_pid_exit(pid, STALE_PROCESS_TERM_TIMEOUT):
            return
        os.kill(pid, signal.SIGKILL)
        if not self._wait_for_pid_exit(pid, STALE_PROCESS_KILL_TIMEOUT):
            raise OSError("stale owned server did not terminate")

    def _wait_for_pid_exit(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while self._pid_alive(pid):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    @classmethod
    def _pid_alive(cls, pid: int) -> bool:
        if cls._windows_host():
            return cls._windows_process_details(pid) is not None
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def _pid_matches_marker(self, pid: int, executable: str, port: int) -> bool:
        if self._windows_host():
            details = self._windows_process_details(pid)
            if details is None:
                return False
            actual_executable, creation_time = details
            try:
                marker = json.loads(self._owner_marker_path.read_text(encoding="utf-8"))
                expected_creation = int(marker["process_creation_time"])
            except (OSError, ValueError, TypeError, KeyError):
                # Incomplete markers cannot safely identify a reused PID.
                return False
            return (
                os.path.normcase(actual_executable) == os.path.normcase(executable)
                and creation_time == expected_creation
            )
        try:
            marker = json.loads(self._owner_marker_path.read_text(encoding="utf-8"))
            expected_start = str(marker["process_start_token"])
        except (OSError, ValueError, TypeError, KeyError):
            return False
        if self._posix_process_start_token(pid) != expected_start:
            return False
        arguments: list[str] = []
        proc_exe = Path(f"/proc/{pid}/exe")
        try:
            if proc_exe.exists():
                if proc_exe.resolve() != Path(executable):
                    return False
                command_line = Path(f"/proc/{pid}/cmdline").read_bytes()
                arguments = [
                    item.decode(errors="replace") for item in command_line.split(b"\0") if item
                ]
        except OSError:
            return False
        if not arguments:
            try:
                result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "command="],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                    shell=False,
                )
                if result.returncode != 0:
                    return False
                arguments = shlex.split(result.stdout.strip())
            except (OSError, ValueError, subprocess.SubprocessError):
                return False
        if not arguments:
            return False
        try:
            actual_executable = Path(arguments[0]).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            return False
        if actual_executable != Path(executable):
            return False
        return any(
            argument == "--port"
            and index + 1 < len(arguments)
            and arguments[index + 1] == str(port)
            for index, argument in enumerate(arguments)
        )

    @staticmethod
    def _posix_process_start_token(pid: int) -> str | None:
        """Return an opaque process-birth token so a reused PID cannot match a marker."""
        if pid <= 0:
            return None
        stat_path = Path(f"/proc/{pid}/stat")
        try:
            if stat_path.exists():
                fields = stat_path.read_text(encoding="utf-8").rsplit(") ", 1)[1].split()
                return fields[19] if len(fields) > 19 else None
        except (OSError, IndexError):
            return None
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.0,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        token = " ".join(result.stdout.split()) if result.returncode == 0 else ""
        return token or None

    @classmethod
    def _windows_process_details(cls, pid: int) -> tuple[str, int] | None:
        """Return executable and creation time without signalling the process."""
        if not cls._windows_host() or pid <= 0:
            return None
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return None
                if exit_code.value != 259:  # STILL_ACTIVE
                    return None
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    return None
                creation = wintypes.FILETIME()
                exit_time = wintypes.FILETIME()
                kernel = wintypes.FILETIME()
                user = wintypes.FILETIME()
                if not kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(exit_time),
                    ctypes.byref(kernel),
                    ctypes.byref(user),
                ):
                    return None
                ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                return str(Path(buffer.value).resolve()), ticks
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None

    @staticmethod
    def _windows_host() -> bool:
        return os.name == "nt"

    @classmethod
    def _windows_process_creation_time(cls, pid: int) -> int | None:
        details = cls._windows_process_details(pid)
        return details[1] if details is not None else None

    @staticmethod
    def _terminate_verified_windows_process(
        pid: int,
        expected_executable: str,
        expected_creation_time: int,
    ) -> None:
        """Verify and terminate through one handle, closing the PID-reuse race."""
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x1001, False, int(pid))  # QUERY_LIMITED | TERMINATE
            if not handle:
                raise OSError(ctypes.get_last_error(), "OpenProcess failed")
            try:
                size = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(size.value)
                creation = wintypes.FILETIME()
                unused = [wintypes.FILETIME() for _ in range(3)]
                if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    raise OSError(ctypes.get_last_error(), "process identity unavailable")
                if not kernel32.GetProcessTimes(
                    handle,
                    ctypes.byref(creation),
                    ctypes.byref(unused[0]),
                    ctypes.byref(unused[1]),
                    ctypes.byref(unused[2]),
                ):
                    raise OSError(ctypes.get_last_error(), "process identity unavailable")
                ticks = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
                actual_executable = str(Path(buffer.value).resolve())
                if (
                    os.path.normcase(actual_executable) != os.path.normcase(expected_executable)
                    or ticks != expected_creation_time
                ):
                    raise OSError("process identity changed")
                if not kernel32.TerminateProcess(handle, 1):
                    raise OSError(ctypes.get_last_error(), "TerminateProcess failed")
            finally:
                kernel32.CloseHandle(handle)
        except AttributeError as exc:
            raise OSError("Windows process API unavailable") from exc

    @staticmethod
    def _safe_error(exc: Exception, fallback: str) -> str:
        text = " ".join(str(exc).split())
        if not text:
            return fallback
        # Do not expose command lines, paths, or multi-line process output.
        if "--" in text or "/" in text or "\\" in text:
            return fallback
        return text[:240]


__all__ = ["LocalAIManager", "LocalAIStateError", "LocalAIStatus"]
