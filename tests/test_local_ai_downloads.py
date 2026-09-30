from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import tarfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from src.local_ai.catalog import BINARY_SPECS, MODELS
from src.local_ai.downloads import (
    DownloadCancelled,
    DownloadError,
    DownloadIntegrityError,
    DownloadSpec,
    binary_companion_archive_path,
    binary_companion_download_spec,
    binary_download_spec,
    download_catalog_artifact,
    download_transfer_complete,
    download_verified,
    draft_download_spec,
    extract_verified_archive,
    install_verified_companion_archive,
    local_ai_dir,
    model_download_spec,
)

PAYLOAD = b"payload"


def _companion_license_fixture(tmp_path: Path) -> tuple[Path, bytes, dict[str, object]]:
    payload = b"fixture NVIDIA CUDA terms\n"
    source = tmp_path / "NVIDIA-CUDA-EULA.txt"
    source.write_bytes(payload)
    return (
        source,
        payload,
        {
            "license_source": source,
            "license_sha256": hashlib.sha256(payload).hexdigest(),
            "license_bytes": len(payload),
            "installed_license_filename": "NVIDIA-CUDA-EULA.txt",
        },
    )


def test_download_preflight_rejects_insufficient_free_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.local_ai.downloads as downloads

    monkeypatch.setattr(
        downloads.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=64 * 1024 * 1024),
    )

    with pytest.raises(DownloadError, match="insufficient free space"):
        downloads._require_download_space(tmp_path, 1)


def test_verified_companion_archive_installs_only_exact_root_dll_set(tmp_path: Path) -> None:
    archive = tmp_path / "cudart.zip"
    members = {
        "cublas64_12.dll": b"cublas",
        "cublasLt64_12.dll": b"cublas-lt",
        "cudart64_12.dll": b"cudart",
    }
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, payload in members.items():
            zipped.writestr(name, payload)
    payload = archive.read_bytes()
    destination = tmp_path / "runtime"
    _license_source, license_payload, license_args = _companion_license_fixture(tmp_path)

    installed = install_verified_companion_archive(
        archive,
        destination,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_bytes=len(payload),
        allowed_members=tuple(members),
        **license_args,
    )

    assert {path.name for path in installed} == set(members)
    assert {path.name: path.read_bytes() for path in installed} == members
    assert (destination / "NVIDIA-CUDA-EULA.txt").read_bytes() == license_payload


def test_verified_companion_archive_rejects_unexpected_member(tmp_path: Path) -> None:
    archive = tmp_path / "cudart.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("cudart64_12.dll", b"cudart")
        zipped.writestr("run-me.exe", b"unexpected")
    payload = archive.read_bytes()
    _license_source, _license_payload, license_args = _companion_license_fixture(tmp_path)

    with pytest.raises(ValueError, match="unexpected companion archive member"):
        install_verified_companion_archive(
            archive,
            tmp_path / "runtime",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            expected_bytes=len(payload),
            allowed_members=("cudart64_12.dll",),
            **license_args,
        )


def test_linux_cuda_companion_installs_exact_nested_regular_files(tmp_path: Path) -> None:
    root = "cudart-llama-b10976-bin-ubuntu-cuda-12.8-x64"
    members = tuple(
        f"{root}/{name}" for name in ("libcudart.so.12", "libcublas.so.12", "libcublasLt.so.12")
    )
    archive = tmp_path / "companion.tar.gz"
    with tarfile.open(archive, "w:gz") as packed:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        packed.addfile(directory)
        for member in members:
            payload = member.encode()
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            packed.addfile(info, io.BytesIO(payload))
    payload = archive.read_bytes()
    destination = tmp_path / "runtime"
    _license_source, license_payload, license_args = _companion_license_fixture(tmp_path)

    installed = install_verified_companion_archive(
        archive,
        destination,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_bytes=len(payload),
        allowed_members=members,
        **license_args,
    )

    assert {path.name for path in installed} == {
        "libcudart.so.12",
        "libcublas.so.12",
        "libcublasLt.so.12",
    }
    assert all(path.is_file() for path in installed)
    assert (destination / "NVIDIA-CUDA-EULA.txt").read_bytes() == license_payload


def test_companion_install_rejects_mismatched_license_before_publication(tmp_path: Path) -> None:
    archive = tmp_path / "cudart.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("cudart64_12.dll", b"cudart")
    archive_payload = archive.read_bytes()
    license_source, license_payload, license_args = _companion_license_fixture(tmp_path)
    destination = tmp_path / "runtime"

    with pytest.raises(DownloadIntegrityError, match="SHA-256 digest mismatch"):
        install_verified_companion_archive(
            archive,
            destination,
            expected_sha256=hashlib.sha256(archive_payload).hexdigest(),
            expected_bytes=len(archive_payload),
            allowed_members=("cudart64_12.dll",),
            **{
                **license_args,
                "license_sha256": hashlib.sha256(license_payload + b"x").hexdigest(),
            },
        )

    assert license_source.is_file()
    assert not destination.exists()


class _FixtureHandler(BaseHTTPRequestHandler):
    payloads: dict[str, bytes] = {"/payload.bin": PAYLOAD, "/large.bin": b"0123456789" * 1000}
    ranges: list[tuple[str, str]] = []
    ignore_range = False
    ignore_if_range = False
    # Preserve the declared total while truncating the body to simulate a
    # server that closes an incomplete transfer without correcting its headers.
    truncate_to: dict[str, int] = {}
    etags: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802
        payload = self.payloads.get(self.path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return

        range_header = self.headers.get("Range")
        type(self).ranges.append((self.path, range_header or ""))
        etag = type(self).etags.get(self.path, f'"{hashlib.sha256(payload).hexdigest()}"')
        if_range = self.headers.get("If-Range")
        range_matches = type(self).ignore_if_range or not if_range or if_range == etag
        if range_header and not type(self).ignore_range and range_matches:
            start = int(range_header.removeprefix("bytes=").split("-", 1)[0])
            body = payload[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
        else:
            body = payload
            self.send_response(200)
        declared_length = len(body)
        truncate = type(self).truncate_to.get(self.path)
        if truncate is not None:
            body = body[:truncate]
        self.send_header("Content-Length", str(declared_length))
        self.send_header("ETag", etag)
        self.end_headers()
        for offset in range(0, len(body), 17):
            self.wfile.write(body[offset : offset + 17])
            self.wfile.flush()

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def http_file_server() -> tuple[str, type]:
    handler = type("FixtureHandler", (_FixtureHandler,), {})
    handler.ranges = []
    handler.ignore_range = False
    handler.ignore_if_range = False
    handler.truncate_to = {}
    handler.etags = {}
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    except PermissionError as exc:
        pytest.skip(f"local HTTP fixture unavailable in this sandbox: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _redirect_requests_to_fixture(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    *canonical_urls: str,
) -> None:
    """Redirect a list of canonical catalog URLs to a local HTTP fixture.

    ``download_catalog_artifact`` enforces the canonical catalog URL on the
    spec, so a real ``download_transfer_complete`` / ``download_verified``
    end-to-end test cannot simply swap the spec URL for the fixture URL.
    Instead, the tests below monkeypatch ``requests.get`` to translate each
    canonical URL into a fixture URL while leaving the rest of the
    downloader code path (catalog validation, ``.part`` handling, SHA-256
    comparison, atomic ``os.replace``) completely unchanged.

    ``base_url`` is the fixture's base URL (e.g. ``http://127.0.0.1:12345``).
    Each ``canonical_url`` is rewritten to ``<base_url>/<canonical path>``:
    the URL path is preserved so the existing ``_FixtureHandler`` route table
    (which keys on the request path) is used unchanged.  The downloader
    sees a real ``requests.Response`` with real headers, real ``iter_content``
    streaming, and real network timeout semantics.
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    fixture_base = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    mapping = {
        canonical: f"{fixture_base}{urlparse(canonical).path}" for canonical in canonical_urls
    }

    def fake_get(url: str, *args: object, **kwargs: object):
        target = mapping.get(url, url)
        # Delegate to a fresh ``requests.Session().get`` instance — using
        # the module-level ``requests.get`` would recurse into ourselves
        # because the monkeypatch above replaced that very attribute on
        # the same module object.  ``Session.get`` calls a private method
        # and never re-enters ``requests.get`` at module scope.
        import requests as _real_requests

        return _real_requests.Session().request("GET", target, *args, **kwargs)

    import src.local_ai.downloads as _dl

    monkeypatch.setattr(_dl.requests, "get", fake_get)


def test_download_rejects_a_digest_mismatch(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "model.gguf"
    with pytest.raises(DownloadIntegrityError, match="SHA-256"):
        download_verified(
            url=f"{base_url}/payload.bin",
            destination=target,
            expected_sha256="0" * 64,
            expected_bytes=len(PAYLOAD),
        )
    assert not target.exists()
    assert target.with_name(target.name + ".part").exists()


def test_download_renames_part_file_only_after_validation(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "model.gguf"
    download_verified(
        url=f"{base_url}/payload.bin",
        destination=target,
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        expected_bytes=len(PAYLOAD),
    )
    assert target.read_bytes() == PAYLOAD
    assert not target.with_name(target.name + ".part").exists()


def test_download_verified_preserves_a_matching_existing_final_without_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "model.gguf"
    target.write_bytes(PAYLOAD)

    def unexpected_request(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a verified existing artifact must not be downloaded again")

    monkeypatch.setattr("src.local_ai.downloads.requests.get", unexpected_request)

    result = download_verified(
        url="https://example.invalid/model.gguf",
        destination=target,
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        expected_bytes=len(PAYLOAD),
    )

    assert result == target
    assert target.read_bytes() == PAYLOAD


def test_download_resumes_only_after_server_acknowledges_range(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    target = tmp_path / "model.gguf"
    part = target.with_name(target.name + ".part")
    part.write_bytes(PAYLOAD[:3])

    download_verified(
        url=f"{base_url}/payload.bin",
        destination=target,
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        expected_bytes=len(PAYLOAD),
    )

    assert handler.ranges == [("/payload.bin", "bytes=3-")]
    assert target.read_bytes() == PAYLOAD


def test_download_restarts_when_server_ignores_range(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    handler.ignore_range = True
    target = tmp_path / "model.gguf"
    target.with_name(target.name + ".part").write_bytes(b"stale")

    download_verified(
        url=f"{base_url}/payload.bin",
        destination=target,
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        expected_bytes=len(PAYLOAD),
    )

    assert handler.ranges == [("/payload.bin", "bytes=5-"), ("/payload.bin", "")]
    assert target.read_bytes() == PAYLOAD


def test_download_cancellation_keeps_part_but_never_publishes_target(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "model.gguf"
    cancelled = Event()

    def progress(downloaded: int, _total: int) -> None:
        if downloaded:
            cancelled.set()

    with pytest.raises(DownloadCancelled, match="cancelled"):
        download_verified(
            url=f"{base_url}/large.bin",
            destination=target,
            expected_sha256=hashlib.sha256(b"0123456789" * 1000).hexdigest(),
            expected_bytes=10_000,
            progress_callback=progress,
            cancel_event=cancelled,
        )
    assert not target.exists()
    assert target.with_name(target.name + ".part").exists()


def test_local_ai_dir_uses_the_explicit_bundle_override(monkeypatch, tmp_path) -> None:
    bundle_root = tmp_path / ".aqa" / "local-ai"
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(bundle_root))
    assert local_ai_dir() == bundle_root.resolve()


def test_catalog_download_spec_is_allow_listed_and_root_contained(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path / "local-ai"))
    spec = model_download_spec("gemma-4-e2b")
    assert isinstance(spec, DownloadSpec)
    assert spec.url == MODELS["gemma-4-e2b"].model_url
    assert (
        spec.destination
        == local_ai_dir() / "models" / "gemma-4-e2b" / MODELS["gemma-4-e2b"].model_filename
    )
    assert spec.destination.is_relative_to(local_ai_dir())
    assert spec.verification == "strict"

    # An attacker-controlled URL or destination must never be allowed through.
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(
            DownloadSpec(
                url="http://127.0.0.1/attacker",
                destination=tmp_path / "outside.bin",
                expected_sha256=spec.expected_sha256,
                expected_bytes=spec.expected_bytes,
                catalog_key=spec.catalog_key,
                verification=spec.verification,
            )
        )


def test_catalog_download_spec_accepts_a_custom_root_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "custom-local-ai"
    spec = model_download_spec("gemma-4-e2b", root=root)
    assert spec.verification == "strict"
    published: list[Path] = []
    transfer_calls: list[Path] = []
    verified_calls: list[Path] = []

    def fake_transfer_complete(url, destination, **_kwargs):
        transfer_calls.append(Path(destination))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fixture")
        published.append(Path(destination))
        return Path(destination)

    def fake_download_verified(**_kwargs):
        destination = Path(_kwargs["destination"])
        verified_calls.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fixture")
        published.append(destination)
        return destination

    monkeypatch.setattr("src.local_ai.downloads.download_transfer_complete", fake_transfer_complete)
    monkeypatch.setattr("src.local_ai.downloads.download_verified", fake_download_verified)
    result = download_catalog_artifact(spec)

    assert result == spec.destination
    assert published == [spec.destination]
    assert transfer_calls == []
    assert verified_calls == [spec.destination]
    assert spec.destination.is_relative_to(root)


def test_catalog_binary_download_spec_accepts_a_custom_root_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "custom-local-ai"
    spec = binary_download_spec("macos-arm64-metal", root=root)
    assert spec.verification == "strict"
    published: list[Path] = []
    transfer_calls: list[Path] = []
    verified_calls: list[Path] = []

    def fake_download_verified(url, destination, **_kwargs):
        verified_calls.append(Path(destination))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fixture")
        published.append(Path(destination))
        return Path(destination)

    def fake_transfer_complete(url, destination, **_kwargs):
        transfer_calls.append(Path(destination))
        return Path(destination)

    monkeypatch.setattr("src.local_ai.downloads.download_verified", fake_download_verified)
    monkeypatch.setattr("src.local_ai.downloads.download_transfer_complete", fake_transfer_complete)
    result = download_catalog_artifact(spec)

    assert result == spec.destination
    assert published == [spec.destination]
    assert verified_calls == [spec.destination]
    # The strict binary spec must never be routed to transfer_complete.
    assert transfer_calls == []
    assert spec.destination.is_relative_to(root)


def test_windows_cuda_companion_has_contained_strict_download_spec(
    tmp_path: Path,
) -> None:
    root = tmp_path / "local-ai"
    spec = binary_companion_download_spec("windows-x86_64-cuda", root=root)

    assert spec == DownloadSpec(
        url=(
            "https://github.com/ggml-org/llama.cpp/releases/download/b10976/"
            "cudart-llama-bin-win-cuda-12.4-x64.zip"
        ),
        destination=binary_companion_archive_path("windows-x86_64-cuda", root=root),
        expected_sha256=("8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
        expected_bytes=391_443_627,
        catalog_key="companion:windows-x86_64-cuda:cudart",
        verification="strict",
    )
    assert spec.destination.is_relative_to(root)


def test_catalog_routes_allow_listed_cuda_companion_to_strict_downloader(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = binary_companion_download_spec("windows-x86_64-cuda", root=tmp_path / "local-ai")
    calls: list[Path] = []

    def fake_download_verified(url, destination, **_kwargs):
        calls.append(Path(destination))
        return Path(destination)

    monkeypatch.setattr("src.local_ai.downloads.download_verified", fake_download_verified)
    result = download_catalog_artifact(spec)

    assert result == spec.destination
    assert calls == [spec.destination]


def test_catalog_routes_model_and_binary_to_strict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "custom-local-ai"
    model_spec = model_download_spec("gemma-4-e2b", root=root)
    binary_spec = binary_download_spec("macos-arm64-metal", root=root)
    transfer_calls: list[Path] = []
    verified_calls: list[Path] = []

    def fake_transfer_complete(url, destination, **_kwargs):
        transfer_calls.append(Path(destination))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fixture")
        return Path(destination)

    def fake_download_verified(url, destination, **_kwargs):
        verified_calls.append(Path(destination))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fixture")
        return Path(destination)

    monkeypatch.setattr("src.local_ai.downloads.download_transfer_complete", fake_transfer_complete)
    monkeypatch.setattr("src.local_ai.downloads.download_verified", fake_download_verified)

    download_catalog_artifact(model_spec)
    download_catalog_artifact(binary_spec)

    assert transfer_calls == []
    assert verified_calls == [model_spec.destination, binary_spec.destination]


def test_catalog_binary_spec_with_bad_digest_routes_to_strict_function(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "custom-local-ai"
    spec = binary_download_spec("macos-arm64-metal", root=root)
    assert spec.verification == "strict"
    transfer_calls: list[Path] = []

    def fake_transfer_complete(url, destination, **_kwargs):
        transfer_calls.append(Path(destination))
        return Path(destination)

    def fake_download_verified(url, destination, **_kwargs):
        # The strict path will compute a SHA-256 over the streamed body and
        # compare it to the spec's digest.  Simulate that mismatch here.
        from src.local_ai.downloads import DownloadIntegrityError

        raise DownloadIntegrityError("SHA-256 digest mismatch")

    monkeypatch.setattr("src.local_ai.downloads.download_transfer_complete", fake_transfer_complete)
    monkeypatch.setattr("src.local_ai.downloads.download_verified", fake_download_verified)

    with pytest.raises(DownloadIntegrityError, match="SHA-256"):
        download_catalog_artifact(spec)
    # Routing proof: the binary spec went to download_verified and was never
    # sent to download_transfer_complete.
    assert transfer_calls == []


def test_catalog_altered_model_url_is_rejected_even_with_matching_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "custom-local-ai"
    spec = model_download_spec("gemma-4-e2b", root=root)
    tampered = DownloadSpec(
        url="http://attacker.example/malicious.gguf",
        destination=spec.destination,
        expected_sha256=spec.expected_sha256,
        expected_bytes=spec.expected_bytes,
        catalog_key=spec.catalog_key,
        verification=spec.verification,
    )
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(tampered)


@pytest.mark.parametrize("field", ["expected_sha256", "expected_bytes"])
def test_catalog_altered_model_identity_is_rejected(field: str, tmp_path: Path) -> None:
    spec = model_download_spec("gemma-4-e2b", root=tmp_path / "local-ai")
    values = {
        "expected_sha256": "0" * 64 if field == "expected_sha256" else spec.expected_sha256,
        "expected_bytes": 1 if field == "expected_bytes" else spec.expected_bytes,
    }
    tampered = DownloadSpec(
        url=spec.url,
        destination=spec.destination,
        expected_sha256=values["expected_sha256"],
        expected_bytes=values["expected_bytes"],
        catalog_key=spec.catalog_key,
        verification="strict",
    )

    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(tampered)


def _write_tar(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_archive_extraction_rejects_parent_traversal_before_writing(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    _write_tar(archive, [("../escape/llama-server", b"bad")])
    destination = tmp_path / "extracted"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="unsafe archive member"):
        extract_verified_archive(
            archive,
            destination,
            expected_sha256=digest,
            expected_bytes=archive.stat().st_size,
            allowed_members=("llama/llama-server",),
        )
    assert not (tmp_path / "escape").exists()
    assert not destination.exists()


def test_archive_extraction_rejects_unsafe_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        link = tarfile.TarInfo("llama/llama-server")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        tar.addfile(link)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(ValueError):
        extract_verified_archive(
            archive,
            tmp_path / "extracted",
            expected_sha256=digest,
            expected_bytes=archive.stat().st_size,
            allowed_members=("llama/llama-server",),
        )


def test_archive_extraction_allows_internal_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "symlinks.tar.gz"
    payload = b"#!/bin/sh\n"
    with tarfile.open(archive, "w:gz") as tar:
        # Real file
        info = tarfile.TarInfo("llama/llama-server")
        info.size = len(payload)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(payload))
        # Shared lib as a real file
        lib_info = tarfile.TarInfo("llama/libggml.0.dylib")
        lib_info.size = len(payload)
        tar.addfile(lib_info, io.BytesIO(payload))
        # Symlink: libggml.dylib -> libggml.0.dylib (safe, internal)
        link = tarfile.TarInfo("llama/libggml.dylib")
        link.type = tarfile.SYMTYPE
        link.linkname = "libggml.0.dylib"
        tar.addfile(link)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    server = extract_verified_archive(
        archive,
        tmp_path / "extracted",
        expected_sha256=digest,
        expected_bytes=archive.stat().st_size,
        allowed_members=("llama/llama-server",),
    )
    assert server.name == "llama-server"
    assert server.read_bytes() == payload

    link_path = tmp_path / "extracted" / "llama" / "libggml.dylib"
    assert link_path.is_symlink()
    assert os.readlink(link_path) == "libggml.0.dylib"
    # The symlink should resolve to the real file
    assert (tmp_path / "extracted" / "llama" / "libggml.0.dylib").is_file()


def test_archive_extraction_supports_zip_and_returns_server(tmp_path: Path) -> None:
    archive = tmp_path / "llama.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        info = zipfile.ZipInfo("llama/llama-server")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        zipped.writestr(info, b"#!/bin/sh\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    server = extract_verified_archive(
        archive,
        tmp_path / "extracted",
        expected_sha256=digest,
        expected_bytes=archive.stat().st_size,
        allowed_members=("llama/llama-server",),
    )
    assert server.name == "llama-server"
    assert server.read_bytes() == b"#!/bin/sh\n"
    assert os.access(server, os.X_OK)


def test_archive_extraction_preserves_allowlisted_license(tmp_path: Path) -> None:
    archive = tmp_path / "llama.tar.gz"
    _write_tar(
        archive,
        [
            ("llama/llama-server", b"#!/bin/sh\n"),
            ("llama/LICENSE", b"upstream license\n"),
        ],
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    server = extract_verified_archive(
        archive,
        tmp_path / "extracted",
        expected_sha256=digest,
        expected_bytes=archive.stat().st_size,
        allowed_members=("llama/llama-server", "llama/LICENSE"),
    )

    assert server.name == "llama-server"
    assert (server.parent / "LICENSE").read_text() == "upstream license\n"


def test_windows_root_zip_accepts_llama_server_and_pe_companions(tmp_path: Path) -> None:
    archive = tmp_path / "llama-b10064-bin-win-cpu-arm64.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, payload in (
            ("llama-server.exe", b"MZ fixture"),
            ("ggml-rpc-server.exe", b"MZ fixture"),
            ("llama-cli.exe", b"MZ fixture"),
            ("ggml.dll", b"dll fixture"),
            ("llama.dll", b"dll fixture"),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            zipped.writestr(info, payload)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    server = extract_verified_archive(
        archive,
        tmp_path / "extracted",
        expected_sha256=digest,
        expected_bytes=archive.stat().st_size,
        allowed_members=("llama-server.exe",),
    )

    assert server.name == "llama-server.exe"
    assert (server.parent / "ggml-rpc-server.exe").read_bytes() == b"MZ fixture"
    assert (server.parent / "llama-cli.exe").read_bytes() == b"MZ fixture"
    assert (server.parent / "ggml.dll").read_bytes() == b"dll fixture"


def test_windows_root_zip_rejects_unexpected_root_file(tmp_path: Path) -> None:
    archive = tmp_path / "llama-b10976-bin-win-cpu-x64.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name in ("llama-server.exe", "unexpected.txt"):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            zipped.writestr(info, b"fixture")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="unexpected archive member"):
        extract_verified_archive(
            archive,
            tmp_path / "extracted",
            expected_sha256=digest,
            expected_bytes=archive.stat().st_size,
            allowed_members=("llama-server.exe",),
        )


# The low-level response-length-only primitive retains resume, cancellation,
# durability, and atomic-publication semantics for non-catalog callers.
def test_transfer_complete_downloads_and_removes_part(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")

    result = download_transfer_complete(
        url=f"{base_url}/payload.bin",
        destination=target,
    )

    assert result == target
    assert target.read_bytes() == PAYLOAD
    assert not part.exists()


def test_transfer_complete_rejects_incomplete_declared_response(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    # Server declares 7 bytes (PAYLOAD length) but only delivers 3, then
    # closes the stream — a typical mid-transfer truncation.
    handler.truncate_to = {"/payload.bin": 3}
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")

    with pytest.raises(DownloadError):
        download_transfer_complete(
            url=f"{base_url}/payload.bin",
            destination=target,
        )

    # No final file is ever published.  The .part is preserved (any partial
    # bytes that made it past the requests buffering layer are still on
    # disk; an empty .part simply means the network error fired before any
    # chunk was yielded to the consumer).
    assert not target.exists()
    assert part.exists()


def test_transfer_complete_resumes_a_valid_206_prefix(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    metadata = target.with_name(target.name + ".part.meta")
    part.write_bytes(PAYLOAD[:3])
    etag = f'"{hashlib.sha256(PAYLOAD).hexdigest()}"'
    metadata.write_text(
        json.dumps(
            {
                "url": f"{base_url}/payload.bin",
                "identity_kind": "etag",
                "identity_value": etag,
                "total": len(PAYLOAD),
            }
        ),
        encoding="utf-8",
    )

    result = download_transfer_complete(
        url=f"{base_url}/payload.bin",
        destination=target,
    )

    assert result == target
    assert target.read_bytes() == PAYLOAD
    assert not part.exists()
    # The request used the resume Range header and the server acknowledged it
    # with 206 starting at the existing size.
    assert handler.ranges == [("/payload.bin", "bytes=3-")]


def test_transfer_complete_restarts_when_upstream_object_changes(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    url = f"{base_url}/payload.bin"
    old_payload = b"old-data"
    new_payload = b"new-data"
    handler.payloads = {**handler.payloads, "/payload.bin": new_payload}
    handler.etags = {"/payload.bin": '"new-object"'}
    target = tmp_path / "mutable.bin"
    target.with_name(target.name + ".part").write_bytes(old_payload[:4])
    target.with_name(target.name + ".part.meta").write_text(
        json.dumps(
            {
                "url": url,
                "identity_kind": "etag",
                "identity_value": '"old-object"',
                "total": len(old_payload),
            }
        ),
        encoding="utf-8",
    )

    result = download_transfer_complete(url=url, destination=target)

    assert result == target
    assert target.read_bytes() == new_payload
    assert handler.ranges == [("/payload.bin", "bytes=4-"), ("/payload.bin", "")]
    assert not target.with_name(target.name + ".part.meta").exists()


def test_transfer_complete_bounds_unidentified_partial_cleanup_denial(
    tmp_path: Path,
    http_file_server: tuple[str, type],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, handler = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    part.write_bytes(b"unidentified-prefix")
    original_unlink = Path.unlink

    def deny_partial_reset(path: Path, *args: object, **kwargs: object) -> None:
        if path == part:
            raise PermissionError("fixture denied partial reset")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_partial_reset)

    with pytest.raises(DownloadError, match="partial state could not be reset"):
        download_transfer_complete(
            url=f"{base_url}/payload.bin",
            destination=target,
        )

    assert not target.exists()
    assert part.read_bytes() == b"unidentified-prefix"
    assert handler.ranges == []


def test_transfer_complete_bounds_changed_identity_cleanup_denial(
    tmp_path: Path,
    http_file_server: tuple[str, type],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, handler = http_file_server
    handler.ignore_if_range = True
    handler.etags = {"/payload.bin": '"new-object"'}
    url = f"{base_url}/payload.bin"
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    metadata = target.with_name(target.name + ".part.meta")
    part.write_bytes(PAYLOAD[:3])
    metadata.write_text(
        json.dumps(
            {
                "url": url,
                "identity_kind": "etag",
                "identity_value": '"old-object"',
                "total": len(PAYLOAD),
            }
        ),
        encoding="utf-8",
    )
    original_unlink = Path.unlink

    def deny_metadata_reset(path: Path, *args: object, **kwargs: object) -> None:
        if path == metadata:
            raise PermissionError("fixture denied metadata reset")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_metadata_reset)

    with pytest.raises(DownloadError, match="partial state could not be reset"):
        download_transfer_complete(url=url, destination=target)

    assert not target.exists()
    assert metadata.is_file()
    assert handler.ranges == [("/payload.bin", "bytes=3-")]


def test_transfer_complete_returns_existing_final_file_directly(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    target.write_bytes(PAYLOAD)
    part.write_bytes(b"different")

    result = download_transfer_complete(
        url=f"{base_url}/payload.bin",
        destination=target,
    )

    assert result == target
    assert target.read_bytes() == PAYLOAD
    assert handler.ranges == []
    # The stray .part is preserved untouched — only the actual destination
    # is the authoritative final artifact.
    assert part.read_bytes() == b"different"


def test_transfer_complete_cancellation_preserves_part_and_never_publishes(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    cancelled = Event()

    def progress(downloaded: int, _total: int) -> None:
        if downloaded:
            cancelled.set()

    with pytest.raises(DownloadCancelled, match="cancelled"):
        download_transfer_complete(
            url=f"{base_url}/large.bin",
            destination=target,
            progress_callback=progress,
            cancel_event=cancelled,
        )

    assert not target.exists()
    assert part.exists()


@pytest.mark.parametrize(
    ("downloader", "target_name"),
    [
        pytest.param(download_verified, "strict-model.gguf", id="strict"),
        pytest.param(download_transfer_complete, "mutable-model.bin", id="transfer-complete"),
    ],
)
def test_download_permission_denial_keeps_partial_and_never_publishes(
    tmp_path: Path,
    http_file_server: tuple[str, type],
    monkeypatch: pytest.MonkeyPatch,
    downloader: Callable[..., Path],
    target_name: str,
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / target_name
    part = target.with_name(target.name + ".part")
    original_open = Path.open

    def denied_open(path: Path, *args: object, **kwargs: object):
        if path == part and kwargs.get("mode", args[0] if args else "r") in {"wb", "ab"}:
            raise PermissionError("fixture denied write permission")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    if downloader is download_verified:
        call = lambda: downloader(  # noqa: E731
            url=f"{base_url}/payload.bin",
            destination=target,
            expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            expected_bytes=len(PAYLOAD),
        )
    else:
        call = lambda: downloader(url=f"{base_url}/payload.bin", destination=target)  # noqa: E731

    with pytest.raises(DownloadError, match="could not be saved"):
        call()
    assert not target.exists()
    assert not part.exists()


@pytest.mark.parametrize(
    ("downloader", "target_name"),
    [
        pytest.param(download_verified, "strict-model.gguf", id="strict"),
        pytest.param(download_transfer_complete, "mutable-model.bin", id="transfer-complete"),
    ],
)
def test_download_interrupted_finalization_preserves_verified_part(
    tmp_path: Path,
    http_file_server: tuple[str, type],
    monkeypatch: pytest.MonkeyPatch,
    downloader: Callable[..., Path],
    target_name: str,
) -> None:
    import src.local_ai.downloads as downloads_module

    base_url, _ = http_file_server
    target = tmp_path / target_name
    part = target.with_name(target.name + ".part")
    real_os = downloads_module.os

    class ReplaceFailureProxy:
        def replace(self, source: object, destination: object, *args: object) -> None:
            if Path(destination) == target:
                raise OSError("fixture interrupted final rename")
            return real_os.replace(source, destination, *args)

        def __getattr__(self, name: str) -> object:
            return getattr(real_os, name)

    monkeypatch.setattr(downloads_module, "os", ReplaceFailureProxy())
    if downloader is download_verified:
        call = lambda: downloader(  # noqa: E731
            url=f"{base_url}/payload.bin",
            destination=target,
            expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            expected_bytes=len(PAYLOAD),
        )
    else:
        call = lambda: downloader(url=f"{base_url}/payload.bin", destination=target)  # noqa: E731

    with pytest.raises(DownloadError, match="could not be installed"):
        call()
    assert not target.exists()
    assert part.read_bytes() == PAYLOAD


def test_transfer_complete_reports_success_when_sidecar_cleanup_fails_after_publish(
    tmp_path: Path,
    http_file_server: tuple[str, type],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    metadata = target.with_name(target.name + ".part.meta")
    original_unlink = Path.unlink

    def fail_metadata_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if path == metadata and target.is_file():
            raise PermissionError("fixture denied post-publish metadata cleanup")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_metadata_cleanup)

    result = download_transfer_complete(
        url=f"{base_url}/payload.bin",
        destination=target,
    )

    assert result == target
    assert target.read_bytes() == PAYLOAD
    assert not part.exists()
    assert metadata.is_file()


def test_download_cancelled_before_bytes_starts_no_transfer(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, handler = http_file_server
    target = tmp_path / "before-bytes.bin"
    cancelled = Event()
    cancelled.set()

    with pytest.raises(DownloadCancelled, match="cancelled"):
        download_transfer_complete(
            url=f"{base_url}/payload.bin", destination=target, cancel_event=cancelled
        )
    assert handler.ranges == []
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_download_cancelled_at_mid_body_barrier_preserves_part(
    tmp_path: Path, http_file_server: tuple[str, type]
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "mid-body.bin"
    cancelled = Event()
    first_chunk = Event()
    release = Event()
    outcome: dict[str, BaseException] = {}

    def progress(downloaded: int, _total: int) -> None:
        if downloaded and not first_chunk.is_set():
            first_chunk.set()
            assert release.wait(timeout=2)

    def run() -> None:
        try:
            download_transfer_complete(
                url=f"{base_url}/large.bin",
                destination=target,
                progress_callback=progress,
                cancel_event=cancelled,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            outcome["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    assert first_chunk.wait(timeout=2)
    cancelled.set()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert isinstance(outcome.get("error"), DownloadCancelled)
    assert not target.exists()
    assert target.with_name(target.name + ".part").exists()


def test_download_cancelled_at_verification_barrier_never_publishes(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.local_ai.downloads as downloads_module

    base_url, _ = http_file_server
    target = tmp_path / "verification.bin"
    cancelled = Event()
    verified = Event()
    original_verify = downloads_module._verify_file

    def verify_then_cancel(*args: object, **kwargs: object) -> None:
        original_verify(*args, **kwargs)
        verified.set()
        cancelled.set()

    monkeypatch.setattr(downloads_module, "_verify_file", verify_then_cancel)
    with pytest.raises(DownloadCancelled, match="cancelled"):
        download_verified(
            url=f"{base_url}/payload.bin",
            destination=target,
            expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            expected_bytes=len(PAYLOAD),
            cancel_event=cancelled,
        )
    assert verified.is_set()
    assert not target.exists()
    assert target.with_name(target.name + ".part").exists()


def test_download_cancelled_at_final_rename_barrier_publishes_atomically(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.local_ai.downloads as downloads_module

    base_url, _ = http_file_server
    target = tmp_path / "final-rename.bin"
    cancelled = Event()
    entered = Event()
    release = Event()
    real_os = downloads_module.os

    class RenameBarrierProxy:
        def replace(self, source: object, destination: object, *args: object) -> None:
            if Path(destination) == target:
                entered.set()
                assert release.wait(timeout=2)
                return real_os.replace(source, destination, *args)
            return real_os.replace(source, destination, *args)

        def __getattr__(self, name: str) -> object:
            return getattr(real_os, name)

    monkeypatch.setattr(downloads_module, "os", RenameBarrierProxy())
    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["path"] = download_transfer_complete(
                url=f"{base_url}/payload.bin", destination=target, cancel_event=cancelled
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            result["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(timeout=2)
    cancelled.set()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result.get("error") is None
    assert result["path"] == target
    assert target.read_bytes() == PAYLOAD
    assert not target.with_name(target.name + ".part").exists()


# Catalogue root derivation fails closed when canonical model or binary path
# anchors drift; assertions intentionally avoid coupling to exact error text.
def test_catalog_validation_rejects_nested_model_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path / "local-ai"))
    e2b = MODELS["gemma-4-e2b"]
    nested = local_ai_dir() / "extra" / "segment" / "models" / e2b.id / e2b.model_filename
    spec = DownloadSpec(
        url=e2b.model_url,
        destination=nested,
        expected_sha256=e2b.model_sha256,
        expected_bytes=e2b.model_bytes,
        catalog_key=f"model:{e2b.id}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_nested_draft_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path / "local-ai"))
    e2b = MODELS["gemma-4-e2b"]
    nested = local_ai_dir() / "extra" / "segment" / "models" / e2b.id / e2b.draft_filename
    spec = DownloadSpec(
        url=e2b.draft_url,
        destination=nested,
        expected_sha256=e2b.draft_sha256,
        expected_bytes=e2b.draft_bytes,
        catalog_key=f"draft:{e2b.id}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_wrong_model_id_in_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    e2b = MODELS["gemma-4-e2b"]
    wrong_dir = tmp_path / "models" / "gemma-4-e4b" / e2b.model_filename
    spec = DownloadSpec(
        url=e2b.model_url,
        destination=wrong_dir,
        expected_sha256=e2b.model_sha256,
        expected_bytes=e2b.model_bytes,
        catalog_key=f"model:{e2b.id}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_missing_models_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    e2b = MODELS["gemma-4-e2b"]
    no_models_dir = tmp_path / e2b.id / e2b.model_filename
    spec = DownloadSpec(
        url=e2b.model_url,
        destination=no_models_dir,
        expected_sha256=e2b.model_sha256,
        expected_bytes=e2b.model_bytes,
        catalog_key=f"model:{e2b.id}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_nested_binary_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AQA_LOCAL_AI_DIR", str(tmp_path / "local-ai"))
    binary = BINARY_SPECS["macos-arm64-metal"]
    nested = (
        local_ai_dir()
        / "extra"
        / "segment"
        / "llama.cpp"
        / binary.release_tag
        / binary.platform
        / binary.archive_filename
    )
    spec = DownloadSpec(
        url=binary.archive_url,
        destination=nested,
        expected_sha256=binary.archive_sha256,
        expected_bytes=binary.archive_bytes,
        catalog_key=f"binary:{binary.profile}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_binary_destination_missing_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]
    altered = (
        tmp_path
        / "llama.cpp"
        / binary.release_tag
        / binary.archive_filename  # platform segment dropped
    )
    spec = DownloadSpec(
        url=binary.archive_url,
        destination=altered,
        expected_sha256=binary.archive_sha256,
        expected_bytes=binary.archive_bytes,
        catalog_key=f"binary:{binary.profile}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_binary_destination_wrong_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]
    altered = (
        tmp_path
        / "llama.cpp"
        / "b9999"  # wrong release tag
        / binary.platform
        / binary.archive_filename
    )
    spec = DownloadSpec(
        url=binary.archive_url,
        destination=altered,
        expected_sha256=binary.archive_sha256,
        expected_bytes=binary.archive_bytes,
        catalog_key=f"binary:{binary.profile}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_rejects_binary_destination_wrong_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = BINARY_SPECS["macos-arm64-metal"]
    altered = (
        tmp_path
        / "llama.cpp"
        / binary.release_tag
        / "linux-x86_64"  # wrong platform for this profile
        / binary.archive_filename
    )
    spec = DownloadSpec(
        url=binary.archive_url,
        destination=altered,
        expected_sha256=binary.archive_sha256,
        expected_bytes=binary.archive_bytes,
        catalog_key=f"binary:{binary.profile}",
        verification="strict",
    )
    _stub_downloaders(monkeypatch)
    with pytest.raises(ValueError, match="catalog"):
        download_catalog_artifact(spec)


def test_catalog_validation_accepts_a_custom_root_with_canonical_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "custom-local-ai"
    model_spec = model_download_spec("gemma-4-e2b", root=root)
    binary_spec = binary_download_spec("macos-arm64-metal", root=root)

    # The destination must end with the canonical anchor: <root>/models/<id>/<file>
    # and <root>/llama.cpp/<release>/<platform>/backends/<profile>/<file>.
    # layouts the hardened validator will accept.
    e2b = MODELS["gemma-4-e2b"]
    assert model_spec.destination == root / "models" / e2b.id / e2b.model_filename
    assert model_spec.destination.parent.name == e2b.id
    assert model_spec.destination.parent.parent.name == "models"

    binary = BINARY_SPECS["macos-arm64-metal"]
    assert binary_spec.destination == (
        root
        / "llama.cpp"
        / binary.release_tag
        / binary.platform
        / "backends"
        / binary.profile
        / binary.archive_filename
    )

    # End-to-end: the custom-root helper specs must still pass
    # _validate_catalog_spec and route to their respective downloader.
    calls = _stub_downloaders(monkeypatch)
    download_catalog_artifact(model_spec)
    download_catalog_artifact(binary_spec)

    assert calls["transfer"] == []
    assert calls["verified"] == [model_spec.destination, binary_spec.destination]


def _stub_downloaders(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Path]]:
    """Stub the catalog downloader primitives and record their invocations.

    Returns a ``calls`` dict with ``"transfer"`` and ``"verified"`` lists of
    destinations.  Tests that exercise ``download_catalog_artifact`` should
    use this helper to ensure invalid catalog input cannot reach a real
    network request or hang the test suite.
    """
    calls: dict[str, list[Path]] = {"transfer": [], "verified": []}

    def fake_transfer_complete(url, destination, **_kwargs):
        calls["transfer"].append(Path(destination))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fixture")
        return Path(destination)

    def fake_download_verified(url, destination, **_kwargs):
        calls["verified"].append(Path(destination))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"fixture")
        return Path(destination)

    monkeypatch.setattr("src.local_ai.downloads.download_transfer_complete", fake_transfer_complete)
    monkeypatch.setattr("src.local_ai.downloads.download_verified", fake_download_verified)
    return calls


# Requests to canonical catalogue URLs are redirected to compact local HTTP
# fixtures so allow-list and routing checks remain active without network I/O.
COMPACT_CHANGED_DRAFTER_PAYLOAD = b"new-upstream-drafter-payload" * 100  # ~2700 bytes


def test_catalog_drafter_rejects_corrupt_content_before_publication(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, handler = http_file_server
    spec = draft_download_spec("gemma-4-e2b", root=tmp_path / "local-ai")
    handler.payloads[_canonical_path(spec.url)] = COMPACT_CHANGED_DRAFTER_PAYLOAD
    _redirect_requests_to_fixture(monkeypatch, base_url, spec.url)

    assert spec.verification == "strict"
    assert len(COMPACT_CHANGED_DRAFTER_PAYLOAD) != spec.expected_bytes
    assert hashlib.sha256(COMPACT_CHANGED_DRAFTER_PAYLOAD).hexdigest() != spec.expected_sha256

    with pytest.raises(DownloadIntegrityError):
        download_catalog_artifact(spec)

    assert not spec.destination.exists()
    assert spec.destination.with_name(spec.destination.name + ".part").is_file()

    assert handler.ranges == [(_canonical_path(spec.url), "")]


def test_catalog_drafter_resume_is_verified_before_publication(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, handler = http_file_server
    payload = COMPACT_CHANGED_DRAFTER_PAYLOAD
    original = MODELS["gemma-4-e2b"]
    monkeypatch.setitem(
        MODELS,
        original.id,
        replace(
            original,
            draft_sha256=hashlib.sha256(payload).hexdigest(),
            draft_bytes=len(payload),
        ),
    )
    spec = draft_download_spec("gemma-4-e2b", root=tmp_path / "local-ai")
    handler.payloads[_canonical_path(spec.url)] = payload

    part = spec.destination.with_name(spec.destination.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(payload[:37])

    _redirect_requests_to_fixture(monkeypatch, base_url, spec.url)

    result = download_catalog_artifact(spec)

    assert result == spec.destination
    assert result.is_file()
    assert result.read_bytes() == payload
    assert not part.exists()
    assert not any(spec.destination.parent.glob("*.part"))

    path = _canonical_path(spec.url)
    assert handler.ranges == [(path, "bytes=37-")]


def test_strict_binary_rejects_bad_payload_via_real_strict_path(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, handler = http_file_server
    spec = binary_download_spec("macos-arm64-metal", root=tmp_path / "local-ai")

    # Sanity: the strict policy is in force for binary specs too.
    assert spec.verification == "strict"
    assert spec.expected_sha256 and len(spec.expected_sha256) == 64
    assert spec.expected_bytes and spec.expected_bytes > 0

    # The fixture body does NOT match the pinned digest or byte count —
    # the SHA-256 over ``b"fixture-binary-archive-payload"`` is not the
    # catalog's pinned digest, and the byte count differs from
    # ``spec.expected_bytes``.  This is the minimum the strict primitive
    # is required to detect.
    fixture_body = b"fixture-binary-archive-payload"
    handler.payloads[_canonical_path(spec.url)] = fixture_body
    assert len(fixture_body) != spec.expected_bytes
    assert hashlib.sha256(fixture_body).hexdigest() != spec.expected_sha256

    # If routing ever weakens the strict path to call
    # ``download_transfer_complete`` for a binary spec, this tripwire
    # fails the test rather than silently passing.
    transfer_calls: list[Path] = []

    def tripwire_transfer_complete(url, destination, **_kwargs):
        transfer_calls.append(Path(destination))
        raise AssertionError("binary spec was incorrectly routed to download_transfer_complete")

    monkeypatch.setattr(
        "src.local_ai.downloads.download_transfer_complete",
        tripwire_transfer_complete,
    )

    _redirect_requests_to_fixture(monkeypatch, base_url, spec.url)

    part = spec.destination.with_name(spec.destination.name + ".part")
    assert not spec.destination.exists()
    assert not part.exists()

    with pytest.raises(DownloadIntegrityError):
        download_catalog_artifact(spec)

    # Strict path failure modes:
    # 1. The final archive is never published.
    assert not spec.destination.exists()
    # 2. The .part sibling is preserved (the partial transfer remains on
    #    disk so a corrected install attempt can replace it).
    assert part.exists()
    # 3. The transfer-only path was never used — proving catalog policy
    #    routing, not merely a generic ``download_verified`` unit test.
    assert transfer_calls == []


def _canonical_path(url: str) -> str:
    """Return the path component of a canonical catalog URL.

    The fixture's :class:`_FixtureHandler` routes on the request path;
    catalog URLs embed a stable path like
    ``/unsloth/gemma-4-E2B-it-qat-GGUF/resolve/<revision>/...`` that we can
    reuse as the fixture key.
    """
    from urllib.parse import urlparse

    return urlparse(url).path


# Windows cannot open directories with O_DIRECTORY. These tests simulate only
# that failure and require both download paths to keep an already-published
# artifact successful.
def _patch_windows_directory_fsync_unavailable(
    monkeypatch: pytest.MonkeyPatch, parent_dir: Path
) -> None:
    """Simulate Windows' inability to ``O_DIRECTORY``-open a parent directory.

    Patches ``src.local_ai.downloads.os`` with a thin wrapper that:

    * reports ``os.name == 'nt'`` so the downloader sees the Windows
      platform tag and can branch on it;
    * delegates *every* other attribute to the real ``os`` module so
      ``os.replace``, ``os.fsync``, ``os.O_RDONLY``, the
      ``O_DIRECTORY`` constant, etc. are still the real things;
    * wraps ``os.open`` so any call whose path resolves to
      ``parent_dir`` raises ``OSError`` — the exact failure mode
      Windows surfaces for an unsupported ``O_DIRECTORY`` flag.

    Why a wrapper and not a bare ``monkeypatch.setattr`` of ``os.name``?
    ``os`` is a single shared module object across the process; setting
    ``os.name = 'nt'`` globally would flip ``pathlib``'s cached
    ``WindowsPath``/``PosixPath`` class selection and break every
    ``Path(...)`` construction in the production code before the
    downloader ever reaches the parent-fsync call.  Scoping the
    Windows tag to ``downloads.os`` (and leaving the real ``os`` module
    alone) keeps ``pathlib`` on ``PosixPath`` so the rest of the
    downloader — streaming, the ``.part`` file, the atomic
    ``os.replace`` publication, the SHA-256 / declared-total checks —
    runs unchanged against the real local HTTP fixture.

    The patch is scoped to the ``downloads`` module so the
    ``monkeypatch`` fixture's automatic teardown restores the original
    ``downloads.os`` binding after the test, even on failure.
    """
    import os as _real_os

    import src.local_ai.downloads as _dl

    parent_resolved = str(parent_dir)

    class _WindowsOsProxy:
        """A minimal ``os`` stand-in that reports ``name == 'nt'`` and
        delegates everything else (including a wrapped ``open``) to the
        real ``os`` module."""

        name = "nt"

        def __init__(self, real_open):  # type: ignore[no-untyped-def]
            self._real_open = real_open

        def open(self, path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(path) == parent_resolved:
                raise OSError(
                    22,  # EINVAL — the same errno Windows surfaces for an
                    # unsupported ``O_DIRECTORY`` flag in its Win32
                    # ``_open`` surface.
                    f"os.open({path!r}, {flags!r}) is not supported on Windows",
                )
            return self._real_open(path, flags, *args, **kwargs)

        def __getattr__(self, item):  # type: ignore[no-untyped-def]
            return getattr(_real_os, item)

    proxy = _WindowsOsProxy(_real_os.open)
    monkeypatch.setattr(_dl, "os", proxy)
    assert _dl.os.name == "nt"
    assert _dl.os.replace is _real_os.replace
    with pytest.raises(OSError):
        _dl.os.open(parent_resolved, _real_os.O_RDONLY)


def test_verified_download_publishes_when_windows_directory_fsync_is_unavailable(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "model.gguf"
    part = target.with_name(target.name + ".part")
    _patch_windows_directory_fsync_unavailable(monkeypatch, target.parent)

    raised: DownloadError | None = None
    result: Path | None = None
    try:
        result = download_verified(
            url=f"{base_url}/payload.bin",
            destination=target,
            expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            expected_bytes=len(PAYLOAD),
        )
    except DownloadError as exc:
        raised = exc

    assert target.is_file()
    assert target.read_bytes() == PAYLOAD
    assert not part.exists()

    assert raised is None, (
        f"download_verified raised {type(raised).__name__}({raised!r}) "
        f"after os.replace published the destination {target}. "
        f"The post-publish directory-fsync is inapplicable on Windows "
        f"and must not turn a successful publication into a raised error."
    )
    assert result == target


def test_transfer_complete_download_publishes_when_windows_directory_fsync_is_unavailable(
    tmp_path: Path, http_file_server: tuple[str, type], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / "mutable.bin"
    part = target.with_name(target.name + ".part")
    _patch_windows_directory_fsync_unavailable(monkeypatch, target.parent)

    raised: DownloadError | None = None
    result: Path | None = None
    try:
        result = download_transfer_complete(
            url=f"{base_url}/payload.bin",
            destination=target,
        )
    except DownloadError as exc:
        raised = exc

    assert target.is_file()
    assert target.read_bytes() == PAYLOAD
    assert not part.exists()

    assert raised is None, (
        f"download_transfer_complete raised {type(raised).__name__}({raised!r}) "
        f"after os.replace published the destination {target}. "
        f"The post-publish directory-fsync is inapplicable on Windows "
        f"and must not turn a successful publication into a raised error."
    )
    assert result == target


# POSIX must fsync the parent after atomic publication. Instrument only
# downloads.os because changing process-wide os state breaks pathlib selection.
def _spy_on_parent_directory_fsync(
    monkeypatch: pytest.MonkeyPatch, parent_dir: Path
) -> tuple[list[str], list[int]]:
    """Wrap ``downloads.os.open`` and ``downloads.os.fsync`` so the test
    can observe — without changing — the helper's real parent-directory
    open + fsync calls.

    Returns ``(parent_open_paths, fsync_fd_calls)``: a list of every
    ``os.open`` path that resolved to ``parent_dir`` and a list of every
    fd passed to ``os.fsync``.  Both lists are mutated by the wrapper as
    the downloader runs, so the test can assert against them after the
    call returns.  All real behaviour is preserved — the wrapper only
    records and delegates to the real ``os`` module, so the helper
    still performs the real ``O_DIRECTORY`` open and the real
    ``fsync`` against the real on-disk directory.
    """
    import os as _real_os

    import src.local_ai.downloads as _dl

    parent_resolved = str(parent_dir)
    parent_open_paths: list[str] = []
    fsync_fd_calls: list[int] = []

    class _PosixOsSpy:
        """Wraps ``os.open`` and ``os.fsync`` to record calls, delegates
        everything else (including ``os.replace``, ``os.O_RDONLY``,
        ``getattr(os, 'O_DIRECTORY', 0)``, ``os.close``) to the real
        ``os`` module so the helper runs unchanged."""

        def open(self, path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(path) == parent_resolved:
                parent_open_paths.append(str(path))
            return _real_os.open(path, flags, *args, **kwargs)

        def fsync(self, fd):  # type: ignore[no-untyped-def]
            fsync_fd_calls.append(int(fd))
            return _real_os.fsync(fd)

        def __getattr__(self, item):  # type: ignore[no-untyped-def]
            return getattr(_real_os, item)

    spy = _PosixOsSpy()
    monkeypatch.setattr(_dl, "os", spy)
    assert _dl.os.name == _real_os.name  # untouched — still "posix"
    assert _dl.os.replace is _real_os.replace
    return parent_open_paths, fsync_fd_calls


@pytest.mark.parametrize(
    "downloader",
    [
        pytest.param(download_verified, id="download_verified"),
        pytest.param(download_transfer_complete, id="download_transfer_complete"),
    ],
)
def test_post_publication_parent_directory_fsync_runs_on_posix(
    tmp_path: Path,
    http_file_server: tuple[str, type],
    monkeypatch: pytest.MonkeyPatch,
    downloader: Callable[..., Path],
) -> None:
    base_url, _ = http_file_server
    target = tmp_path / ("strict-model.gguf" if downloader is download_verified else "mutable.bin")
    parent_open_paths, fsync_fd_calls = _spy_on_parent_directory_fsync(monkeypatch, target.parent)

    if downloader is download_verified:
        result = downloader(
            url=f"{base_url}/payload.bin",
            destination=target,
            expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
            expected_bytes=len(PAYLOAD),
        )
    else:
        result = downloader(
            url=f"{base_url}/payload.bin",
            destination=target,
        )

    assert result == target
    assert target.is_file()
    assert target.read_bytes() == PAYLOAD
    assert not target.with_name(target.name + ".part").exists()

    assert parent_open_paths == [str(target.parent)], (
        f"expected exactly one os.open for the parent directory "
        f"{target.parent!s}, observed: {parent_open_paths!r}"
    )
    # Durability requires one fsync before replacement and one on the parent.
    assert len(fsync_fd_calls) >= 2, (
        f"expected at least two os.fsync calls (one for the .part "
        f"file and one for the parent directory); observed: "
        f"{fsync_fd_calls!r}"
    )
