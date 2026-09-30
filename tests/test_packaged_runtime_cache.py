"""Tests for safe reuse and refresh of packaged CPython runtime bases."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_RUNTIME = PROJECT_ROOT / "packaging" / "runtime" / "verify_runtime.py"
FETCH_RUNTIMES = PROJECT_ROOT / "packaging" / "runtime" / "fetch_runtimes.sh"
PLATFORM = "macos-arm64"
EXPECTED_SHA = "804c86c8665b18eb0df5070a79d828229018d145baea38a71a5c74c03f9b11d4"


def _write_valid_runtime(root: Path, *, marker: str = "original") -> Path:
    runtime = root / PLATFORM
    (runtime / "bin").mkdir(parents=True)
    (runtime / "lib" / "python3.13" / "encodings").mkdir(parents=True)
    (runtime / "include" / "python3.13").mkdir(parents=True)
    (runtime / "bin" / "python3").write_text(marker, encoding="utf-8")
    (runtime / "bin" / "python3.13").write_text(marker, encoding="utf-8")
    (runtime / "lib" / "python3.13" / "os.py").write_text("# stdlib\n", encoding="utf-8")
    (runtime / "lib" / "python3.13" / "encodings" / "__init__.py").write_text(
        "# encodings\n", encoding="utf-8"
    )
    (runtime / "include" / "python3.13" / "patchlevel.h").write_text(
        '#define PY_VERSION "3.13.14"\n', encoding="utf-8"
    )
    return runtime


def _make_archive(tmp_path: Path) -> Path:
    source_root = tmp_path / "archive-source"
    source = _write_valid_runtime(source_root, marker="downloaded")
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source, arcname="payload")
    return archive


def _make_fake_commands(tmp_path: Path, archive: Path, *, bad_hash: bool = False) -> Path:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$AQA_FETCH_LOG"\n'
        'cp "$AQA_TEST_ARCHIVE" "$3"\n',
        encoding="utf-8",
    )
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    shasum = fake_bin / "shasum"
    digest = "0" * 64 if bad_hash else EXPECTED_SHA
    shasum.write_text(
        f'#!/usr/bin/env bash\nprintf "%s  %s\\n" "{digest}" "$3"\n',
        encoding="utf-8",
    )
    shasum.chmod(shasum.stat().st_mode | stat.S_IXUSR)
    return fake_bin


def _run_fetch(
    tmp_path: Path, runtime_root: Path, archive: Path, *, force: str = "0", bad_hash: bool = False
) -> subprocess.CompletedProcess[str]:
    fake_bin = _make_fake_commands(tmp_path, archive, bad_hash=bad_hash)
    fetch_log = tmp_path / "fetch.log"
    env = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "PYTHON_FOR_TOOLS": sys.executable,
        "RUNTIME_DIR": str(runtime_root),
        "RUNTIME_PLATFORM": PLATFORM,
        "RUNTIME_FORCE": force,
        "AQA_TEST_ARCHIVE": str(archive),
        "AQA_FETCH_LOG": str(fetch_log),
    }
    result = subprocess.run(
        ["bash", str(FETCH_RUNTIMES)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    result.fetch_log = fetch_log  # type: ignore[attr-defined]
    return result


def test_validate_base_accepts_complete_pinned_runtime(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write_valid_runtime(runtime_root)

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME),
            "validate-base",
            "--runtime-root",
            str(runtime_root),
            "--platform",
            PLATFORM,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "BASE_RUNTIME_VALID: macos-arm64" in result.stdout


def test_validate_base_rejects_stale_or_incomplete_runtime(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    runtime = _write_valid_runtime(runtime_root)
    header = runtime / "include" / "python3.13" / "patchlevel.h"
    header.write_text('#define PY_VERSION "3.13.13"\n', encoding="utf-8")

    stale = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME),
            "validate-base",
            "--runtime-root",
            str(runtime_root),
            "--platform",
            PLATFORM,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert stale.returncode == 1
    assert "expected 3.13.14, got 3.13.13" in stale.stderr

    header.write_text('#define PY_VERSION "3.13.14"\n', encoding="utf-8")
    (runtime / "lib" / "python3.13" / "os.py").unlink()
    incomplete = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME),
            "validate-base",
            "--runtime-root",
            str(runtime_root),
            "--platform",
            PLATFORM,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert incomplete.returncode == 1
    assert "missing file lib/python3.13/os.py" in incomplete.stderr


def test_fetch_reuses_valid_runtime_without_download(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write_valid_runtime(runtime_root)
    archive = _make_archive(tmp_path)

    result = _run_fetch(tmp_path, runtime_root, archive)

    assert result.returncode == 0, result.stderr
    assert "Existing runtime passed base validation; reusing." in result.stdout
    assert not result.fetch_log.exists()  # type: ignore[attr-defined]


def test_fetch_replaces_invalid_runtime_and_preserves_old_runtime_on_bad_archive(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime = _write_valid_runtime(runtime_root)
    (runtime / "include" / "python3.13" / "patchlevel.h").write_text(
        '#define PY_VERSION "3.13.13"\n', encoding="utf-8"
    )
    archive = _make_archive(tmp_path)

    replaced = _run_fetch(tmp_path, runtime_root, archive)

    assert replaced.returncode == 0, replaced.stderr
    assert "Existing runtime is incomplete or stale; downloading a replacement." in replaced.stdout
    assert replaced.fetch_log.exists()  # type: ignore[attr-defined]
    assert (runtime_root / PLATFORM / "bin" / "python3").read_text(encoding="utf-8") == "downloaded"

    original = (runtime_root / PLATFORM / "bin" / "python3").read_text(encoding="utf-8")
    failed = _run_fetch(tmp_path, runtime_root, archive, force="1", bad_hash=True)

    assert failed.returncode != 0
    assert "SHA-256 mismatch" in failed.stderr
    assert (runtime_root / PLATFORM / "bin" / "python3").read_text(encoding="utf-8") == original


def test_fetch_force_refreshes_valid_runtime(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write_valid_runtime(runtime_root)
    archive = _make_archive(tmp_path)

    result = _run_fetch(tmp_path, runtime_root, archive, force="1")

    assert result.returncode == 0, result.stderr
    assert "Refreshing existing runtime because RUNTIME_FORCE=1" in result.stdout
    assert result.fetch_log.exists()  # type: ignore[attr-defined]
    assert (runtime_root / PLATFORM / "bin" / "python3").read_text(encoding="utf-8") == "downloaded"
