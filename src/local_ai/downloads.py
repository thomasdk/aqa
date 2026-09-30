"""Safe Local AI artifact downloads, catalog paths, and archive extraction.

The low-level downloader is intentionally useful with local HTTP fixtures.  Product
code should use the catalog helpers below, which bind the remote URL, checksum, and
local destination to immutable catalog entries.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform as system_platform
import posixpath
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import requests

from src.config.user_data import local_ai_dir_path

from .catalog import (
    MODELS,
    BinaryCompanionKind,
    BinarySpec,
    ModelSpec,
    binary_for_profile,
    companion_for_binary,
)

ProgressCallback = Callable[[int, int], None]
Verification = Literal["strict", "transfer_complete"]
_DOWNLOAD_SPACE_RESERVE_BYTES = 64 * 1024 * 1024


class DownloadError(RuntimeError):
    """A sanitized network or local download failure."""


class DownloadCancelled(DownloadError):
    """Raised when a caller cancels an in-progress download."""


class DownloadIntegrityError(DownloadError):
    """Raised when a downloaded artifact has the wrong size or SHA-256 digest."""


@dataclass(frozen=True)
class DownloadSpec:
    """A download binding produced by a catalog helper.

    ``catalog_key`` is checked against the current catalog before a download is
    started.  Keeping the key lets application code pass an opaque artifact
    description without accepting a user-supplied URL or filesystem destination.

    ``verification`` selects the downloader primitive:

    * ``'strict'`` — the allow-listed llama.cpp archive path.  The spec must
      carry a 64-hex ``expected_sha256`` and a non-negative ``expected_bytes``
      that the strict :func:`download_verified` will compare against the
      streamed body.  Any drift raises :class:`DownloadIntegrityError`.
    * ``'transfer_complete'`` — a response-length-only path retained for the
      low-level fixture-tested primitive. Catalog model, draft, runtime, and
      companion assets all use strict verification.

    For transfer-only specs, ``expected_sha256`` and ``expected_bytes`` are
    stored as ``None`` so the shared dataclass shape is unambiguous; the strict
    path will reject ``None`` values up front.
    """

    url: str
    destination: Path
    expected_sha256: str | None
    expected_bytes: int | None
    catalog_key: str
    verification: Verification = "strict"

    def __post_init__(self) -> None:
        if not isinstance(self.destination, Path):
            object.__setattr__(self, "destination", Path(self.destination))
        if self.verification not in ("strict", "transfer_complete"):
            raise ValueError("verification must be 'strict' or 'transfer_complete'")
        if self.verification == "strict":
            if not isinstance(self.expected_sha256, str) or not re.fullmatch(
                r"[0-9a-fA-F]{64}", self.expected_sha256
            ):
                raise ValueError("expected_sha256 must be a SHA-256 hex digest")
            if (
                isinstance(self.expected_bytes, bool)
                or not isinstance(self.expected_bytes, int)
                or self.expected_bytes < 0
            ):
                raise ValueError("expected_bytes must be a non-negative integer")
        else:
            if self.expected_sha256 is not None:
                raise ValueError("transfer_complete specs must not carry an expected_sha256")
            if self.expected_bytes is not None:
                raise ValueError("transfer_complete specs must not carry an expected_bytes")


def local_ai_dir() -> Path:
    """Return the per-user Local AI root without creating or reading app settings."""
    configured = local_ai_dir_path()
    if configured is not None:
        return configured

    operating_system = system_platform.system().lower()
    if operating_system == "darwin":
        return (Path.home() / "Library" / "Application Support" / "AQA" / "local-ai").resolve()
    if operating_system == "windows":
        base = os.environ.get("LOCALAPPDATA")
        return (
            Path(base) if base else Path.home() / "AppData" / "Local" / "AQA"
        ).expanduser().resolve() / "local-ai"

    base = os.environ.get("XDG_DATA_HOME")
    data_home = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return (data_home / "aqa" / "local-ai").resolve()


def bundled_third_party_license_path(filename: str) -> Path:
    """Resolve a shipped third-party license in source or packaged layouts."""
    if not filename or PurePosixPath(filename).name != filename:
        raise ValueError("third-party license filename is invalid")
    backend_root = Path(__file__).resolve().parents[2]
    candidates = (
        backend_root / "licenses" / "third-party" / filename,
        backend_root / "THIRD_PARTY_LICENSES" / filename,
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise DownloadError("required third-party license is unavailable")


def _root(root: Path | None) -> Path:
    return local_ai_dir() if root is None else Path(root).expanduser().resolve()


def _contained(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    resolved = Path(candidate).expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("destination must be inside the Local AI directory") from exc
    return resolved


def _model(model_id: str) -> ModelSpec:
    try:
        return MODELS[model_id]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown Local AI model in catalog") from exc


def artifact_path_for_model(model_id: str, *, root: Path | None = None) -> Path:
    model = _model(model_id)
    return _contained(_root(root), _root(root) / "models" / model.id / model.model_filename)


def artifact_path_for_draft(model_id: str, *, root: Path | None = None) -> Path:
    model = _model(model_id)
    return _contained(_root(root), _root(root) / "models" / model.id / model.draft_filename)


def _binary_spec(profile: str | BinarySpec) -> BinarySpec:
    if isinstance(profile, BinarySpec):
        return profile
    return binary_for_profile(profile)


def binary_archive_path(profile: str | BinarySpec, *, root: Path | None = None) -> Path:
    binary = _binary_spec(profile)
    base = _root(root)
    return _contained(
        base,
        base
        / "llama.cpp"
        / binary.release_tag
        / binary.platform
        / "backends"
        / binary.profile
        / binary.archive_filename,
    )


def binary_companion_archive_path(
    profile: str | BinarySpec,
    kind: BinaryCompanionKind = "cudart",
    *,
    root: Path | None = None,
) -> Path:
    """Return the contained archive path for an allow-listed companion."""
    binary = _binary_spec(profile)
    companion = companion_for_binary(binary, kind)
    base = _root(root)
    return _contained(
        base,
        base
        / "llama.cpp"
        / companion.release_tag
        / binary.platform
        / "backends"
        / binary.profile
        / companion.archive_filename,
    )


def binary_extract_path(profile: str | BinarySpec, *, root: Path | None = None) -> Path:
    binary = _binary_spec(profile)
    base = _root(root)
    return _contained(
        base,
        base
        / "llama.cpp"
        / binary.release_tag
        / binary.platform
        / "backends"
        / binary.profile
        / "extracted",
    )


def model_download_spec(model_id: str, *, root: Path | None = None) -> DownloadSpec:
    """A revision-pinned Gemma model spec with exact file identity."""
    model = _model(model_id)
    return DownloadSpec(
        url=model.model_url,
        destination=artifact_path_for_model(model.id, root=root),
        expected_sha256=model.model_sha256,
        expected_bytes=model.model_bytes,
        catalog_key=f"model:{model.id}",
        verification="strict",
    )


def draft_download_spec(model_id: str, *, root: Path | None = None) -> DownloadSpec:
    """A revision-pinned Gemma drafter spec with exact file identity."""
    model = _model(model_id)
    return DownloadSpec(
        url=model.draft_url,
        destination=artifact_path_for_draft(model.id, root=root),
        expected_sha256=model.draft_sha256,
        expected_bytes=model.draft_bytes,
        catalog_key=f"draft:{model.id}",
        verification="strict",
    )


def binary_download_spec(profile: str | BinarySpec, *, root: Path | None = None) -> DownloadSpec:
    """A strict llama.cpp archive spec — exact SHA-256 + byte count required."""
    binary = _binary_spec(profile)
    return DownloadSpec(
        url=binary.archive_url,
        destination=binary_archive_path(binary, root=root),
        expected_sha256=binary.archive_sha256,
        expected_bytes=binary.archive_bytes,
        catalog_key=f"binary:{binary.profile}",
        verification="strict",
    )


def binary_companion_download_spec(
    profile: str | BinarySpec,
    kind: BinaryCompanionKind = "cudart",
    *,
    root: Path | None = None,
) -> DownloadSpec:
    """A strict spec for one allow-listed binary companion archive."""
    binary = _binary_spec(profile)
    companion = companion_for_binary(binary, kind)
    return DownloadSpec(
        url=companion.archive_url,
        destination=binary_companion_archive_path(binary, kind, root=root),
        expected_sha256=companion.archive_sha256,
        expected_bytes=companion.archive_bytes,
        catalog_key=f"companion:{binary.profile}:{companion.kind}",
        verification="strict",
    )


def download_spec_for_model(
    model_id: str, artifact: str = "model", *, root: Path | None = None
) -> DownloadSpec:
    if artifact == "model":
        return model_download_spec(model_id, root=root)
    if artifact == "draft":
        return draft_download_spec(model_id, root=root)
    raise ValueError("unknown catalog model artifact")


def download_spec_for_binary(profile: str, *, root: Path | None = None) -> DownloadSpec:
    return binary_download_spec(profile, root=root)


def _catalog_spec(catalog_key: str, root: Path | None) -> DownloadSpec:
    kind, _, key = catalog_key.partition(":")
    if kind == "model":
        return model_download_spec(key, root=root)
    if kind == "draft":
        return draft_download_spec(key, root=root)
    if kind == "binary":
        return binary_download_spec(key, root=root)
    if kind == "companion":
        profile, separator, companion_kind = key.partition(":")
        if not separator or companion_kind != "cudart":
            raise ValueError("unknown catalog download")
        return binary_companion_download_spec(profile, "cudart", root=root)
    raise ValueError("unknown catalog download")


def _catalog_root_for_destination(spec: DownloadSpec, destination: Path) -> Path:
    """Derive and validate the catalog root from a helper-built destination.

    The catalog publishes two fixed layouts:

    * ``<root>/models/<model_id>/<model-or-draft filename>`` for model/draft.
    * ``<root>/llama.cpp/<release>/<platform>/backends/<profile>/<archive>`` for runtimes.

    This helper verifies the destination's structural anchors — the leaf
    filename, the model id / release / platform segments, and the literal
    ``models`` / ``llama.cpp`` directory — *before* deriving the catalog
    root.  Any deviation in those anchors raises :class:`ValueError` so the
    calling validator fails closed rather than deriving a root from a
    tampered layout.

    Root derivation uses the default ``local_ai_dir()`` when the
    destination is contained under it (the common case) and falls back to
    the helper-trusted ``destination.parents[N]`` derivation only for
    explicit custom roots. Nested paths still have to match the catalog
    anchors; arbitrary parent segments cannot define a valid custom root.
    """
    kind, _, key = spec.catalog_key.partition(":")
    if kind == "model" or kind == "draft":
        try:
            model = _model(key)
        except ValueError as exc:
            raise ValueError("download specification does not match the catalog") from exc
        expected_filename = model.model_filename if kind == "model" else model.draft_filename
        if destination.name != expected_filename:
            raise ValueError("download specification does not match the catalog")
        parent = destination.parent
        if len(parent.parts) < 2 or parent.parts[-2] != "models" or parent.parts[-1] != model.id:
            raise ValueError("download specification does not match the catalog")
        return _derive_catalog_root(destination, depth=2, anchor="models")
    if kind == "binary":
        try:
            binary = _binary_spec(key)
        except ValueError as exc:
            raise ValueError("download specification does not match the catalog") from exc
        if destination.name != binary.archive_filename:
            raise ValueError("download specification does not match the catalog")
        parent = destination.parent
        if (
            len(parent.parts) < 5
            or parent.parts[-5] != "llama.cpp"
            or parent.parts[-4] != binary.release_tag
            or parent.parts[-3] != binary.platform
            or parent.parts[-2] != "backends"
            or parent.parts[-1] != binary.profile
        ):
            raise ValueError("download specification does not match the catalog")
        return _derive_catalog_root(destination, depth=5, anchor="llama.cpp")
    if kind == "companion":
        profile, separator, companion_kind = key.partition(":")
        if not separator or companion_kind != "cudart":
            raise ValueError("download specification does not match the catalog")
        try:
            binary = _binary_spec(profile)
            companion = companion_for_binary(binary, "cudart")
        except (TypeError, ValueError) as exc:
            raise ValueError("download specification does not match the catalog") from exc
        parent = destination.parent
        if (
            destination.name != companion.archive_filename
            or len(parent.parts) < 5
            or parent.parts[-5] != "llama.cpp"
            or parent.parts[-4] != companion.release_tag
            or parent.parts[-3] != binary.platform
            or parent.parts[-2] != "backends"
            or parent.parts[-1] != binary.profile
        ):
            raise ValueError("download specification does not match the catalog")
        return _derive_catalog_root(destination, depth=5, anchor="llama.cpp")
    raise ValueError("unknown catalog download")


def _derive_catalog_root(destination: Path, *, depth: int, anchor: str) -> Path:
    """Derive the catalog root from a structurally-validated destination.

    The structural anchors have already been verified by
    :func:`_catalog_root_for_destination`; this helper is responsible only
    for choosing the correct root.

    For the default root (``local_ai_dir()``), the destination must be
    exactly ``<local_ai_dir()>/<anchor>/...`` with no extra intermediate
    components.  A nested layout like
    ``<local_ai_dir()>/extra/segment/models/<model_id>/<file>`` would
    produce a ``parents[depth]`` that is a strict subdirectory of
    ``local_ai_dir()`` — that is the failure mode the validator must
    reject, because the spec's destination would not match what a
    catalog helper would build under the default root.

    For destinations outside ``local_ai_dir()`` (explicit custom roots),
    the helper trusts ``destination.parents[depth]`` as the root, on the
    assumption that the caller invoked the helper with that root.
    """
    default_root = local_ai_dir()
    parents_root = destination.parents[depth]
    try:
        destination.relative_to(default_root)
    except ValueError:
        # Destination is outside the default root — treat as a custom
        # root and trust the depth-based derivation.
        return parents_root
    # Destination is under the default root.  The derived root must be
    # exactly ``default_root``; any extra intermediate components between
    # the default root and the ``models`` / ``llama.cpp`` anchor are a
    # layout drift and must be rejected.
    if parents_root != default_root:
        raise ValueError("download specification does not match the catalog")
    return default_root


def _validate_catalog_spec(spec: DownloadSpec) -> None:
    """Validate a helper-created spec, including helper-selected custom roots.

    Strict catalog specs must agree on URL, destination, digest, byte count,
    and policy. The transfer-complete branch remains defensive for low-level
    callers but is not used by current catalog entries.

    The catalog root is derived from the destination *only after* the
    canonical path anchors (literal ``models`` / ``llama.cpp`` segments and
    the model id, release tag, platform, and filename from the catalog) are
    verified against the destination.  A layout drift — extra nested
    segment, missing anchor, wrong model id / release / platform / filename
    — fails closed here rather than silently deriving a different root.
    """
    destination = Path(spec.destination).expanduser().resolve()
    root = _catalog_root_for_destination(spec, destination)
    expected = _catalog_spec(spec.catalog_key, root)

    if spec.url != expected.url or destination != expected.destination:
        raise ValueError("download specification does not match the catalog")
    if spec.verification != expected.verification:
        raise ValueError("download specification does not match the catalog")
    if expected.verification == "strict":
        if (
            spec.expected_sha256 is None
            or expected.expected_sha256 is None
            or spec.expected_sha256.lower() != expected.expected_sha256.lower()
            or spec.expected_bytes != expected.expected_bytes
        ):
            raise ValueError("download specification does not match the catalog")
    _contained(root, spec.destination)


def download_catalog_artifact(
    spec: DownloadSpec,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_event: object | None = None,
) -> Path:
    """Download a spec made by a catalog helper, never an arbitrary URL/path.

    Routing is driven by ``spec.verification``: strict specs go through
    :func:`download_verified` (SHA-256 + byte count required); transfer-only
    specs go through :func:`download_transfer_complete` (response-declared
    total is the only integrity evidence).  The catalog validation enforces
    the policy the spec claims, so routing cannot accidentally weaken the
    native binary archive path.
    """
    if not isinstance(spec, DownloadSpec):
        raise TypeError("spec must be a DownloadSpec")
    _validate_catalog_spec(spec)
    if spec.verification == "strict":
        return download_verified(
            url=spec.url,
            destination=spec.destination,
            expected_sha256=spec.expected_sha256 or "",
            expected_bytes=spec.expected_bytes if spec.expected_bytes is not None else 0,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )
    return download_transfer_complete(
        url=spec.url,
        destination=spec.destination,
        progress_callback=progress_callback,
        cancel_event=cancel_event,
    )


def _is_cancelled(cancel_event: object | None) -> bool:
    return bool(
        cancel_event is not None
        and callable(getattr(cancel_event, "is_set", None))
        and cancel_event.is_set()
    )


def _cancel_if_requested(cancel_event: object | None) -> None:
    if _is_cancelled(cancel_event):
        raise DownloadCancelled("download cancelled")


def _part_path(destination: Path) -> Path:
    return destination.with_name(destination.name + ".part")


def _part_metadata_path(destination: Path) -> Path:
    return destination.with_name(destination.name + ".part.meta")


def _response_identity(response: requests.Response) -> tuple[str, str] | None:
    etag = response.headers.get("ETag", "").strip()
    if etag and not etag.lower().startswith("w/"):
        return "etag", etag
    last_modified = response.headers.get("Last-Modified", "").strip()
    if last_modified:
        return "last_modified", last_modified
    return None


def _read_resume_metadata(path: Path, url: str) -> dict[str, object] | None:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict) or metadata.get("url") != url:
        return None
    kind = metadata.get("identity_kind")
    value = metadata.get("identity_value")
    total = metadata.get("total")
    if kind not in ("etag", "last_modified") or not isinstance(value, str) or not value:
        return None
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        return None
    return metadata


def _write_resume_metadata(
    path: Path, url: str, identity: tuple[str, str] | None, total: int
) -> None:
    metadata = {
        "url": url,
        "identity_kind": identity[0] if identity else None,
        "identity_value": identity[1] if identity else None,
        "total": total,
    }
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(metadata, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DownloadError("download resume metadata could not be saved") from exc


def _discard_partial_state(part: Path, metadata_path: Path) -> None:
    try:
        part.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
    except OSError as exc:
        raise DownloadError("download partial state could not be reset") from exc


def _content_range_total(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes\s+\d+-\d+/(\d+|\*)", value.strip(), re.IGNORECASE)
    if not match or match.group(1) == "*":
        return None
    return int(match.group(1))


def _content_range_start(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes\s+(\d+)-\d+/(?:\d+|\*)", value.strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _response_total(response: requests.Response, existing: int, fallback: int) -> int:
    total = _content_range_total(response.headers.get("Content-Range"))
    if total is not None:
        return total
    try:
        content_length = int(response.headers.get("Content-Length", ""))
    except ValueError:
        content_length = 0
    return existing + content_length if content_length > 0 else fallback


def _require_download_space(destination: Path, remaining_bytes: int) -> None:
    """Fail before streaming when the managed volume cannot finish safely."""
    try:
        free_bytes = shutil.disk_usage(destination.parent).free
    except OSError as exc:
        raise DownloadError("download storage could not be inspected") from exc
    required = max(0, int(remaining_bytes)) + _DOWNLOAD_SPACE_RESERVE_BYTES
    if free_bytes < required:
        raise DownloadError("insufficient free space for download")


def _open_response(
    url: str, existing: int, *, if_range: str | None = None
) -> tuple[requests.Response, bool]:
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    if existing and if_range:
        headers["If-Range"] = if_range
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=(10, 60))
    except requests.RequestException as exc:
        raise DownloadError("download request failed") from exc

    if (
        existing
        and response.status_code == 206
        and _content_range_start(response.headers.get("Content-Range")) == existing
    ):
        return response, True

    if existing:
        # A 200 response means the server ignored Range.  Restart from byte zero.
        response.close()
        try:
            response = requests.get(url, stream=True, timeout=(10, 60))
        except requests.RequestException as exc:
            raise DownloadError("download request failed") from exc
    return response, False


def _open_transfer_response(
    url: str, part: Path, metadata_path: Path
) -> tuple[requests.Response, bool, int, tuple[str, str] | None]:
    try:
        existing = part.stat().st_size if part.is_file() else 0
    except OSError as exc:
        raise DownloadError("download partial state could not be inspected") from exc
    metadata = _read_resume_metadata(metadata_path, url) if existing else None
    if existing and metadata is None:
        _discard_partial_state(part, metadata_path)
        existing = 0

    if_range = str(metadata["identity_value"]) if metadata is not None else None
    response, resumed = _open_response(url, existing, if_range=if_range)
    _raise_for_status(response)
    identity = _response_identity(response)
    if resumed and metadata is not None:
        expected_identity = (
            str(metadata["identity_kind"]),
            str(metadata["identity_value"]),
        )
        response_total = _content_range_total(response.headers.get("Content-Range"))
        if identity != expected_identity or response_total != metadata["total"]:
            response.close()
            _discard_partial_state(part, metadata_path)
            existing = 0
            resumed = False
            try:
                response = requests.get(url, stream=True, timeout=(10, 60))
            except requests.RequestException as exc:
                raise DownloadError("download request failed") from exc
            _raise_for_status(response)
            identity = _response_identity(response)
    if not resumed and response.status_code != 200:
        response.close()
        raise DownloadError("server returned a partial response without a valid resume")
    return response, resumed, existing, identity


def _report_existing_file(path: Path, progress_callback: ProgressCallback | None) -> None:
    if progress_callback is None:
        return
    try:
        final_bytes = path.stat().st_size
    except OSError:
        final_bytes = 0
    progress_callback(final_bytes, final_bytes)


def _raise_for_status(response: requests.Response) -> None:
    if response.status_code not in (200, 206):
        response.close()
        raise DownloadError(f"download failed with HTTP status {response.status_code}")


def _verify_file(path: Path, expected_sha256: str, expected_bytes: int) -> None:
    try:
        actual_bytes = path.stat().st_size
    except OSError as exc:
        raise DownloadError("downloaded artifact could not be inspected") from exc
    if actual_bytes != expected_bytes:
        raise DownloadIntegrityError(
            f"byte count mismatch: expected {expected_bytes}, received {actual_bytes}"
        )

    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise DownloadError("downloaded artifact could not be verified") from exc
    if digest.hexdigest().lower() != expected_sha256.lower():
        raise DownloadIntegrityError("SHA-256 digest mismatch")


def _fsync_parent_directory(destination: Path) -> None:
    """Best-effort durability fsync of the parent directory of ``destination``.

    After an atomic ``os.replace(part, destination)`` the file's bytes are
    durably committed, but the *directory entry* may still be in the
    page cache.  ``os.fsync`` on a directory descriptor forces the
    directory's metadata (including the new entry for ``destination``) to
    stable storage, so a power-cut immediately after the publish
    observes the file rather than a stale or missing entry.

    This is a no-op on Windows (``os.name == 'nt'``):

    * the Win32 ``_open`` surface does not honour the POSIX
      ``O_DIRECTORY`` flag and surfaces ``EINVAL`` for an unsupported
      flag combination, so the open+fsync sequence fails for a reason
      unrelated to the publication's success;
    * the parent-directory durability guarantee is a POSIX durability
      contract; Windows' ``MoveFileEx`` / ``ReplaceFile`` semantics
      already durably commit the rename on NTFS, so the fsync is not
      needed there and would only introduce a false install error.

    On POSIX the parent directory is opened read-only with the
    ``O_DIRECTORY`` flag (when available — some POSIX-y platforms lack it; the
    ``getattr(os, "O_DIRECTORY", 0)`` lookup
    degrades to a plain ``O_RDONLY`` open in that case, which is still
    a directory on POSIX because directories cannot be opened for
    reading as files), then ``fsync``-ed, then closed.  Any
    ``OSError`` from these calls is intentionally **not** caught here
    — the caller (``download_verified`` / ``download_transfer_complete``)
    owns the bounded ``DownloadError`` translation in the surrounding
    ``except OSError`` block, so the existing error messages are
    preserved exactly.  The Windows short-circuit is a clean
    ``return`` with no exception flow, so a non-POSIX platform never
    reaches the open.
    """
    if os.name == "nt":
        return
    directory_fd = os.open(str(destination.parent), getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def download_verified(
    url: str,
    destination: Path,
    expected_sha256: str,
    expected_bytes: int,
    progress_callback: ProgressCallback | None = None,
    cancel_event: object | None = None,
) -> Path:
    """Stream, resume, verify, and atomically publish one HTTP artifact.

    This primitive deliberately accepts local fixture URLs.  Application code must
    use ``DownloadSpec`` helpers and ``download_catalog_artifact`` for allow-list
    enforcement.
    """
    if not isinstance(url, str) or not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("download URL must use HTTP or HTTPS")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be a SHA-256 hex digest")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
    ):
        raise ValueError("expected_bytes must be a non-negative integer")

    destination = Path(destination)
    part = _part_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # If the final destination already exists and matches the expected
    # SHA-256 and byte size, skip the download entirely.  This prevents
    # re-downloading multi-gigabyte model files on repeated install attempts
    # or server restarts.
    if destination.is_file():
        try:
            _verify_file(destination, expected_sha256, expected_bytes)
            if progress_callback is not None:
                progress_callback(expected_bytes, expected_bytes)
            return destination
        except (DownloadIntegrityError, DownloadError):
            destination.unlink(missing_ok=True)

    existing = part.stat().st_size if part.is_file() else 0
    _cancel_if_requested(cancel_event)

    response, resumed = _open_response(url, existing)
    try:
        _raise_for_status(response)
        total = _response_total(response, existing if resumed else 0, expected_bytes)
        _require_download_space(destination, total - (existing if resumed else 0))
        if progress_callback is not None:
            progress_callback(existing if resumed else 0, total)
        mode = "ab" if resumed else "wb"
        with part.open(mode) as output:
            downloaded = existing if resumed else 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                _cancel_if_requested(cancel_event)
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                if progress_callback is not None:
                    progress_callback(downloaded, total)
            output.flush()
            os.fsync(output.fileno())
    except DownloadCancelled:
        raise
    except (OSError, requests.RequestException) as exc:
        raise DownloadError("download could not be saved") from exc
    finally:
        response.close()

    _cancel_if_requested(cancel_event)
    _verify_file(part, expected_sha256, expected_bytes)
    _cancel_if_requested(cancel_event)
    try:
        os.replace(part, destination)
        _fsync_parent_directory(destination)
    except OSError as exc:
        raise DownloadError("verified artifact could not be installed") from exc
    return destination


def download_transfer_complete(
    url: str,
    destination: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_event: object | None = None,
) -> Path:
    """Stream, resume, verify, and atomically publish a *mutable* HTTP artifact.

    This is the transfer-complete sibling of :func:`download_verified` for Local
    AI artifacts whose authoritative identity is the response body itself
    (Content-Range / Content-Length) rather than a separately published
    SHA-256.  It is only safe to call against trusted mutable sources — the
    catalog-driven :func:`download_catalog_artifact` path always uses
    :func:`download_verified` instead.

    Behaviour matches :func:`download_verified`:

    * streams into a ``.part`` sibling and atomically ``os.replace``s it;
    * resumes via ``Range: bytes=<existing>-`` when a ``.part`` is present;
    * restarts from byte zero if the server replies ``200 OK`` to a Range request;
    * fsyncs the part and its parent directory before publishing;
    * honours ``cancel_event`` and preserves the ``.part`` on cancellation;
    * an already-published final regular file at ``destination`` is returned
      directly; a stray ``.part`` is **not** treated as the final artifact.

    After streaming, the byte count on disk (the resumed prefix plus the
    newly written body) is compared to the response's declared total — the
    ``/`` field of ``Content-Range`` for ``206`` responses, or
    ``Content-Length`` for ``200`` responses.  A positive declared total is
    required; on any short or over-count the ``.part`` is preserved, the final
    file is never created, and a bounded :class:`DownloadError` is raised.
    """
    if not isinstance(url, str) or not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("download URL must use HTTP or HTTPS")

    destination = Path(destination)
    part = _part_path(destination)
    resume_metadata_path = _part_metadata_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Already-published final file: short-circuit.  A stray .part is
    # intentionally NOT treated as final — the regular file at ``destination``
    # is the authoritative artifact.
    if destination.is_file():
        _report_existing_file(destination, progress_callback)
        return destination

    _cancel_if_requested(cancel_event)

    response, resumed, existing, response_identity = _open_transfer_response(
        url, part, resume_metadata_path
    )
    try:
        total = _response_total(response, existing if resumed else 0, 0)
        if total <= 0:
            response.close()
            raise DownloadError(
                "server did not declare a complete Content-Range or Content-Length total"
            )
        expected_total = total
        if not resumed:
            _write_resume_metadata(resume_metadata_path, url, response_identity, total)
        _require_download_space(destination, total - (existing if resumed else 0))
        if progress_callback is not None:
            progress_callback(existing if resumed else 0, total)
        mode = "ab" if resumed else "wb"
        with part.open(mode) as output:
            downloaded = existing if resumed else 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                _cancel_if_requested(cancel_event)
                if not chunk:
                    continue
                output.write(chunk)
                downloaded += len(chunk)
                if progress_callback is not None:
                    progress_callback(downloaded, total)
            output.flush()
            os.fsync(output.fileno())
    except DownloadCancelled:
        raise
    except (OSError, requests.RequestException) as exc:
        raise DownloadError("download could not be saved") from exc
    finally:
        response.close()

    _cancel_if_requested(cancel_event)
    # Validate the resumed prefix and new bytes against the declared total together.
    try:
        part_size = part.stat().st_size
    except OSError as exc:
        raise DownloadError("downloaded artifact could not be inspected") from exc
    if part_size != expected_total:
        raise DownloadError(
            "download did not complete: declared total "
            f"{expected_total} bytes but received {part_size}"
        )
    _cancel_if_requested(cancel_event)
    try:
        os.replace(part, destination)
        _fsync_parent_directory(destination)
    except OSError as exc:
        raise DownloadError("transfer-complete artifact could not be installed") from exc
    try:
        resume_metadata_path.unlink(missing_ok=True)
    except OSError:
        # The atomic rename is the publication commit point.  A stale sidecar
        # is ignored without its matching .part and must not turn an installed
        # artifact into a reported failure.
        pass
    return destination


def _safe_member_name(name: str) -> str:
    if not name or "\x00" in name:
        raise ValueError("unsafe archive member")
    normalized = name.replace("\\", "/")
    if (
        normalized.startswith("/")
        or normalized.startswith("//")
        or re.match(r"^[A-Za-z]:($|/)", normalized)
    ):
        raise ValueError("unsafe archive member")
    parts = normalized.split("/")
    if ".." in parts:
        raise ValueError("unsafe archive member")
    normalized = posixpath.normpath(normalized)
    if normalized in ("", ".") or normalized.startswith("../"):
        raise ValueError("unsafe archive member")
    return normalized.rstrip("/")


def _allowed_member(name: str, allowed: Sequence[str]) -> bool:
    if name in allowed:
        return True
    for item in allowed:
        parents = PurePosixPath(item).parents
        if any(name == parent.as_posix() for parent in parents):
            return True
    return False


def _safe_symlink_target(link_name: str, target: str) -> str:
    """Reject symlinks that escape the archive root via absolute or traversal targets."""
    safe_target = _safe_member_name(target) if not target.startswith("/") else ""
    if not safe_target:
        raise ValueError("archive symlink has an unsafe target")
    # Keep this independent containment check if member-name validation changes.
    if safe_target.startswith("../"):
        raise ValueError("archive symlink target escapes archive root")
    return safe_target


@dataclass
class _ArchiveMemberValidator:
    """Track archive-member validation for one extraction request."""

    allowed: tuple[str, ...]
    prefixes: tuple[str, ...]
    seen: set[str]
    server_member: str | None = None

    @classmethod
    def create(cls, allowed_members: Iterable[str]) -> _ArchiveMemberValidator:
        allowed = tuple(_safe_member_name(member) for member in allowed_members)
        if not allowed:
            raise ValueError("archive allow-list is empty")
        prefixes = tuple(
            parent + "/"
            for member in allowed
            if (parent := PurePosixPath(member).parent.as_posix()) not in {"", "."}
        )
        return cls(allowed=allowed, prefixes=prefixes, seen=set())

    def validate(self, name: str, kind: str, symlink_target: str | None = None) -> str:
        safe_name = _safe_member_name(name)
        if safe_name in self.seen:
            raise ValueError("duplicate archive member")
        self.seen.add(safe_name)
        if kind == "special":
            raise ValueError("archive special file is not allowed")
        if kind == "symlink":
            if symlink_target is None:
                raise ValueError("archive symlink is missing target")
            # Reject symlinks that point outside the archive root (absolute
            # paths or traversal).  Internal relative symlinks like
            # "libggml.dylib -> libggml.0.dylib" are needed by the
            # llama-server binary and are preserved.
            _safe_symlink_target(safe_name, symlink_target)
        elif not _allowed_member(safe_name, self.allowed) and not any(
            safe_name.startswith(prefix) for prefix in self.prefixes
        ):
            # Windows release zips keep llama-server.exe, its DLLs, and the
            # other signed release executables together at the archive root.
            # The catalog names the server executable; accept only root-level
            # PE companions, never arbitrary files or nested paths.
            root_member = "/" not in safe_name and any("/" not in item for item in self.allowed)
            if not (root_member and PurePosixPath(safe_name).suffix.lower() in {".dll", ".exe"}):
                raise ValueError("unexpected archive member")
        if kind == "file" and PurePosixPath(safe_name).name in {"llama-server", "llama-server.exe"}:
            self.server_member = safe_name
        return safe_name


def _validate_tar_members(archive: Path, validator: _ArchiveMemberValidator) -> None:
    """Validate every member in a gzip-compressed runtime archive."""

    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                if member.issym() or member.islnk():
                    validator.validate(member.name, "symlink", symlink_target=member.linkname)
                elif member.isdir():
                    validator.validate(member.name, "directory")
                elif member.isreg():
                    validator.validate(member.name, "file")
                else:
                    validator.validate(member.name, "special")
    except (OSError, tarfile.TarError) as exc:
        raise DownloadError("archive could not be read") from exc


def _validate_zip_members(archive: Path, validator: _ArchiveMemberValidator) -> None:
    """Validate every member in a ZIP runtime archive."""

    try:
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    target = zipped.read(info).decode("utf-8", errors="replace")
                    validator.validate(info.filename, "symlink", symlink_target=target)
                elif info.is_dir() or mode == stat.S_IFDIR:
                    validator.validate(info.filename, "directory")
                elif mode not in (0, stat.S_IFREG):
                    validator.validate(info.filename, "special")
                else:
                    validator.validate(info.filename, "file")
    except (OSError, zipfile.BadZipFile) as exc:
        raise DownloadError("archive could not be read") from exc


def _validate_archive_members(archive: Path, allowed_members: Iterable[str]) -> tuple[str, ...]:
    validator = _ArchiveMemberValidator.create(allowed_members)

    if archive.name.endswith((".tar.gz", ".tgz")):
        _validate_tar_members(archive, validator)
    elif archive.name.endswith(".zip"):
        _validate_zip_members(archive, validator)
    else:
        raise ValueError("unsupported archive format")

    if validator.server_member is None:
        raise ValueError("archive does not contain llama-server")
    return (validator.server_member,)


def extract_verified_archive(
    archive: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    allowed_members: Iterable[str],
) -> Path:
    """Verify an archive, validate every member, then extract atomically."""
    archive = Path(archive)
    destination = Path(destination)
    _verify_file(archive, expected_sha256, expected_bytes)
    server_member = _validate_archive_members(archive, tuple(allowed_members))[0]

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("archive destination already exists")
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=str(destination.parent)))
    try:
        if archive.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar.getmembers():
                    name = _safe_member_name(member.name)
                    target = stage / name
                    if member.issym() or member.islnk():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists() or target.is_symlink():
                            target.unlink()
                        os.symlink(member.linkname, target)
                    elif member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = tar.extractfile(member)
                        if source is None:
                            raise DownloadError("archive member could not be read")
                        with source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
        else:
            with zipfile.ZipFile(archive) as zipped:
                for info in zipped.infolist():
                    name = _safe_member_name(info.filename)
                    target = stage / name
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == stat.S_IFLNK:
                        link_target = zipped.read(info).decode("utf-8", errors="replace")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.exists() or target.is_symlink():
                            target.unlink()
                        os.symlink(link_target, target)
                    elif info.is_dir() or mode == stat.S_IFDIR:
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zipped.open(info) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)

        server = stage / server_member
        if not server.is_file() or server.is_symlink():
            raise DownloadError("llama-server was not extracted as a regular file")
        os.chmod(server, server.stat().st_mode | stat.S_IXUSR)
        os.replace(stage, destination)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return destination / server_member


def install_verified_companion_archive(  # noqa: C901
    archive: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    allowed_members: Iterable[str],
    license_source: Path,
    license_sha256: str,
    license_bytes: int,
    installed_license_filename: str,
) -> tuple[Path, ...]:
    """Verify and stage an exact CUDA companion set with its matched terms."""
    archive = Path(archive)
    destination = Path(destination)
    _verify_file(archive, expected_sha256, expected_bytes)
    license_source = Path(license_source)
    if not license_source.is_file() or license_source.is_symlink():
        raise DownloadError("required third-party license is unavailable")
    _verify_file(license_source, license_sha256, license_bytes)
    installed_license_filename = _safe_member_name(installed_license_filename)
    if "/" in installed_license_filename:
        raise ValueError("companion license filename is invalid")
    allowed = tuple(_safe_member_name(member) for member in allowed_members)
    if not allowed:
        raise ValueError("companion archive allow-list is invalid")
    if len(set(allowed)) != len(allowed):
        raise ValueError("companion archive allow-list is invalid")
    if installed_license_filename in {PurePosixPath(member).name for member in allowed}:
        raise ValueError("companion license filename is invalid")
    windows_zip = archive.name.endswith(".zip")
    linux_tar = archive.name.endswith((".tar.gz", ".tgz"))
    if not windows_zip and not linux_tar:
        raise ValueError("unsupported companion archive format")
    if windows_zip and (
        any("/" in member for member in allowed)
        or any(PurePosixPath(member).suffix.lower() != ".dll" for member in allowed)
    ):
        raise ValueError("companion archive allow-list is invalid")
    if linux_tar:
        parents = {PurePosixPath(member).parent.as_posix() for member in allowed}
        if len(parents) != 1 or ".so." not in " ".join(allowed):
            raise ValueError("companion archive allow-list is invalid")

    try:
        if windows_zip:
            with zipfile.ZipFile(archive) as zipped:
                infos = zipped.infolist()
                entries = [(info, _safe_member_name(info.filename)) for info in infos]
                for info, name in entries:
                    mode = (info.external_attr >> 16) & 0o170000
                    if info.is_dir() or mode == stat.S_IFDIR or mode == stat.S_IFLNK:
                        raise ValueError("unexpected companion archive member")
                    if mode not in (0, stat.S_IFREG) or name not in allowed:
                        raise ValueError("unexpected companion archive member")

                def opener(info: object) -> object:
                    return zipped.open(info)  # type: ignore[arg-type]

                _install_companion_entries(
                    entries,
                    opener,
                    allowed,
                    destination,
                    license_source=license_source,
                    license_sha256=license_sha256,
                    license_bytes=license_bytes,
                    installed_license_filename=installed_license_filename,
                )
                return tuple(destination / PurePosixPath(name).name for name in allowed)
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            regular = []
            allowed_parent = next(iter({PurePosixPath(item).parent.as_posix() for item in allowed}))
            for member in members:
                name = _safe_member_name(member.name)
                if member.isdir() and name == allowed_parent:
                    continue
                if not member.isreg() or name not in allowed:
                    raise ValueError("unexpected companion archive member")
                regular.append((member, name))

            def opener(member: object) -> object:
                return tar.extractfile(member)  # type: ignore[arg-type]

            _install_companion_entries(
                regular,
                opener,
                allowed,
                destination,
                license_source=license_source,
                license_sha256=license_sha256,
                license_bytes=license_bytes,
                installed_license_filename=installed_license_filename,
            )
            return tuple(destination / PurePosixPath(name).name for name in allowed)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise DownloadError("companion archive could not be read") from exc


def _install_companion_entries(
    entries: Sequence[tuple[object, str]],
    opener: Callable[[object], object],
    allowed: tuple[str, ...],
    destination: Path,
    *,
    license_source: Path,
    license_sha256: str,
    license_bytes: int,
    installed_license_filename: str,
) -> None:
    names = [name for _, name in entries]
    if len(names) != len(set(names)) or set(names) != set(allowed):
        raise ValueError("companion archive members are incomplete")
    destination.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".companion-", dir=str(destination.parent)))
    try:
        for entry, name in entries:
            source = opener(entry)
            if source is None:
                raise DownloadError("companion archive member could not be read")
            target = stage / PurePosixPath(name).name
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
        staged_license = stage / installed_license_filename
        shutil.copyfile(license_source, staged_license)
        _verify_file(staged_license, license_sha256, license_bytes)
        for name in allowed:
            source = stage / PurePosixPath(name).name
            if not source.is_file() or source.is_symlink() or source.stat().st_size <= 0:
                raise DownloadError("companion archive member could not be installed")
            os.replace(source, destination / source.name)
        os.replace(staged_license, destination / installed_license_filename)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def extract_catalog_binary(
    profile: str, *, root: Path | None = None, archive: Path | None = None
) -> Path:
    """Verify and extract a catalog binary into a root-contained install path."""
    binary = binary_for_profile(profile)
    base = _root(root)
    archive_path = (
        binary_archive_path(binary.profile, root=base)
        if archive is None
        else _contained(base, Path(archive))
    )
    destination = binary_extract_path(binary.profile, root=base)
    return extract_verified_archive(
        archive_path,
        destination,
        expected_sha256=binary.archive_sha256,
        expected_bytes=binary.archive_bytes,
        allowed_members=binary.archive_members,
    )


__all__ = [
    "DownloadCancelled",
    "DownloadError",
    "DownloadIntegrityError",
    "DownloadSpec",
    "artifact_path_for_draft",
    "artifact_path_for_model",
    "binary_archive_path",
    "binary_companion_archive_path",
    "binary_companion_download_spec",
    "binary_download_spec",
    "binary_extract_path",
    "bundled_third_party_license_path",
    "download_catalog_artifact",
    "download_spec_for_binary",
    "download_spec_for_model",
    "download_verified",
    "draft_download_spec",
    "extract_catalog_binary",
    "extract_verified_archive",
    "install_verified_companion_archive",
    "local_ai_dir",
    "model_download_spec",
]
