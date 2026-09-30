"""Provenance tests for the embedded Python runtime and dependency lock.

These tests pin the project to a single CPython release (3.13.14 from
the astral-sh/python-build-standalone 20260623 build) and assert the exact
contents of the assets we ship:
  * ``requirements-runtime.in`` is the human-authored list of direct deps.
  * ``requirements-runtime.txt`` is the fully pinned, hashed lock file that
    must install cleanly with ``pip --require-hashes``.
  * ``fetch_runtimes.sh`` declares a fetch table of six platforms in a
    documented order, each with a non-empty 64-hex SHA-256 digest.
  * ``packaging/runtime/verify_runtime.py`` exports an
    ``EXPECTED_PYTHON_VERSION`` constant and rejects readiness receipts whose
    ``python_version`` or ``expected_python_version`` field does not match it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Append the packaging tree to sys.path so we can import the verify script
# as a module and pull out the ``EXPECTED_PYTHON_VERSION`` constant the
# production contract requires.
VERIFY_RUNTIME_PATH = PROJECT_ROOT / "packaging" / "runtime" / "verify_runtime.py"
sys.path.insert(0, str(VERIFY_RUNTIME_PATH.parent))
_spec = importlib.util.spec_from_file_location("packaged_verify_runtime", VERIFY_RUNTIME_PATH)
assert _spec is not None and _spec.loader is not None
verify_runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_runtime)

EXPECTED_PYTHON_VERSION = verify_runtime.EXPECTED_PYTHON_VERSION
FETCH_PLATFORMS = verify_runtime.FETCH_PLATFORMS  # type: ignore[attr-defined]
PLATFORM_DIGESTS = verify_runtime.PLATFORM_DIGESTS  # type: ignore[attr-defined]

REQUIREMENTS_IN = PROJECT_ROOT / "requirements-runtime.in"
REQUIREMENTS_LOCK = PROJECT_ROOT / "requirements-runtime.txt"
FETCH_RUNTIMES_SH = PROJECT_ROOT / "packaging" / "runtime" / "fetch_runtimes.sh"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_NAME_LOCAL = ".aqa-runtime-ready.json"
DIRECT_DEPS = (
    "fastapi",
    "loguru",
    "pydantic",
    "pydantic-settings",
    "python-dotenv",
    "pyyaml",
    "requests",
    "uvicorn",
)
DOCUMENTED_RUNTIME_PLATFORMS = (
    "macos-arm64",
    "macos-x86_64",
    "windows-arm64",
    "windows-x86_64",
    "linux-arm64",
    "linux-x86_64",
)


# Python version pin
def test_expected_python_version_constant_is_3_13_14() -> None:
    assert EXPECTED_PYTHON_VERSION == "3.13.14"


# requirements-runtime.in (direct deps, no pins, no hashes)
def test_requirements_runtime_in_lists_every_direct_dependency() -> None:
    assert REQUIREMENTS_IN.is_file(), (
        f"missing {REQUIREMENTS_IN}; it must list direct dependencies without pins"
    )
    body = REQUIREMENTS_IN.read_text(encoding="utf-8")
    # Comments (#) and blank lines are allowed; pins (==) are not.
    seen: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" not in line, (
            f"requirements-runtime.in must not contain pinned versions: {line!r}"
        )
        assert "--hash" not in line, f"requirements-runtime.in must not contain hashes: {line!r}"
        seen.append(line)
    assert seen == list(DIRECT_DEPS), (
        "requirements-runtime.in must list the exact direct dependencies in "
        f"the documented order, got {seen!r}"
    )


# requirements-runtime.txt (lock with pins + sha256)
def test_requirements_runtime_lock_is_pinned_with_hashes() -> None:
    assert REQUIREMENTS_LOCK.is_file(), (
        f"missing {REQUIREMENTS_LOCK}; must be regenerated via uv pip compile"
    )
    body = REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    # The lock uses pip's "line-continuation" form: the package==version line
    # ends with a trailing " \", and each --hash line may also end with " \".
    # We extract the pin+version by matching the head of each pin line.
    pins = re.findall(
        r"^\s*([A-Za-z0-9_.\-]+)==([^\s]+)",
        body,
        flags=re.MULTILINE,
    )
    hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", body)
    assert pins, "requirements-runtime.txt must contain at least one pinned package"
    assert hashes, "requirements-runtime.txt must contain at least one --hash=sha256: line"
    assert len(hashes) >= len(pins), (
        "every pin in requirements-runtime.txt must be accompanied by a sha256 hash"
    )


def test_requirements_runtime_lock_pins_every_direct_dependency() -> None:
    body = REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    pinned_names = {
        match.group(1).lower().replace("_", "-")
        for match in re.finditer(r"^\s*([A-Za-z0-9_.\-]+)==", body, flags=re.MULTILINE)
    }
    for dep in DIRECT_DEPS:
        normalized_name = dep.lower().replace("_", "-")
        assert normalized_name in pinned_names, (
            f"requirements-runtime.txt is missing a pin for {dep} "
            f"(normalized: {normalized_name}); have {sorted(pinned_names)}"
        )


def test_requirements_runtime_lock_preserves_windows_only_markers() -> None:
    body = REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    for package in ("colorama", "win32-setctime"):
        assert re.search(
            rf"^{re.escape(package)}==[^\n]+; sys_platform == 'win32'",
            body,
            flags=re.MULTILINE,
        ), f"{package} must retain its Windows-only marker"


def test_requirements_runtime_lock_hashes_verify() -> None:
    body = REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    lines = body.splitlines()
    pin_indexes: list[int] = []
    for index, line in enumerate(lines):
        if re.match(r"^\s*[A-Za-z0-9_.\-]+==", line):
            pin_indexes.append(index)
    assert pin_indexes, "no package lines discovered in lock file"
    for index in pin_indexes:
        # Walk forward from the pin to collect the hashes that belong to it.
        collected: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and re.match(r"^\s*--hash=sha256:", lines[cursor]):
            collected.extend(re.findall(r"--hash=sha256:([0-9a-f]{64})", lines[cursor]))
            cursor += 1
        assert collected, (
            f"no sha256 hashes for {lines[index]!r} — every pin must carry at least one"
        )
        for digest in collected:
            assert HEX64.match(digest), f"bad sha256 digest in block for {lines[index]!r}"


# fetch_runtimes.sh (six platforms, three fields each, 64-hex digests)
def _parse_fetch_runtimes_entries() -> list[tuple[str, str, str]]:
    """Extract (platform, url, sha256) triples from fetch_runtimes.sh.

    The script is a plain bash file using only bash-3.2-compatible syntax, so
    we parse the PLATFORMS array with a focused regex rather than executing it.
    """
    body = FETCH_RUNTIMES_SH.read_text(encoding="utf-8")
    triple = re.compile(
        r'^\s*"(?P<platform>[A-Za-z0-9_-]+)\|(?P<url>https?://[^"]+)\|(?P<sha256>[0-9a-f]{64})"\s*$',
        flags=re.MULTILINE,
    )
    return [(m["platform"], m["url"], m["sha256"]) for m in triple.finditer(body)]


def test_fetch_table_has_exactly_six_platforms_in_documented_order() -> None:
    entries = _parse_fetch_runtimes_entries()
    platforms = [entry[0] for entry in entries]
    assert FETCH_PLATFORMS == DOCUMENTED_RUNTIME_PLATFORMS
    assert platforms == list(DOCUMENTED_RUNTIME_PLATFORMS), (
        f"fetch_runtimes.sh must declare exactly {len(DOCUMENTED_RUNTIME_PLATFORMS)} "
        f"platforms in this order: {list(DOCUMENTED_RUNTIME_PLATFORMS)}; got {platforms!r}"
    )


def test_fetch_table_digests_are_nonempty_64_hex() -> None:
    for platform, url, sha256 in _parse_fetch_runtimes_entries():
        assert HEX64.match(sha256), (
            f"{platform}: digest must be 64 lowercase hex chars, got {sha256!r}"
        )
        assert url.startswith("https://github.com/astral-sh/python-build-standalone/"), (
            f"{platform}: URL must point at python-build-standalone, got {url!r}"
        )


def test_fetch_table_matches_verify_runtime_digests() -> None:
    script_digests = dict(
        (platform, sha256) for platform, _url, sha256 in _parse_fetch_runtimes_entries()
    )
    assert set(script_digests) == set(PLATFORM_DIGESTS), (
        f"fetch_runtimes.sh and verify_runtime.py disagree on platforms: "
        f"script={sorted(script_digests)} verify={sorted(PLATFORM_DIGESTS)}"
    )
    for platform, expected in PLATFORM_DIGESTS.items():
        assert script_digests[platform] == expected, (
            f"digest mismatch for {platform}: script={script_digests[platform]} verify={expected}"
        )


# Receipt validation: stale 3.13.12 receipt must fail
def _make_receipt(tmp_path: Path, *, python_version: str) -> tuple[Path, Path]:
    """Build one target runtime and receipt stamped with ``python_version``."""
    runtime_root = tmp_path / "runtime"
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("fastapi\n", encoding="utf-8")
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    platform = "macos-arm64"
    runtime_dir = runtime_root / platform
    executable = runtime_dir / "bin" / "python3"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"fixture runtime placeholder")
    receipt = {
        "schema": 1,
        "platform": platform,
        "python_version": python_version,
        "expected_python_version": EXPECTED_PYTHON_VERSION,
        "requirements_sha256": digest,
        "imports_ok": True,
        "import_check": {"success": True},
    }
    (runtime_dir / RECEIPT_NAME_LOCAL).write_text(json.dumps(receipt), encoding="utf-8")
    return runtime_root, requirements


def test_validate_one_rejects_stale_receipt_with_wrong_python_version(
    tmp_path: Path,
) -> None:
    runtime_root, requirements = _make_receipt(tmp_path, python_version="3.13.12")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME_PATH),
            "validate-one",
            "--runtime-root",
            str(runtime_root),
            "--requirements",
            str(requirements),
            "--platform",
            "macos-arm64",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, (
        "validate-one must reject a receipt whose python_version is not 3.13.14; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "python_version" in result.stderr, (
        f"expected python_version to be flagged in stderr; got {result.stderr!r}"
    )


def test_validate_one_rejects_receipt_with_wrong_expected_python_version(
    tmp_path: Path,
) -> None:
    runtime_root, requirements = _make_receipt(tmp_path, python_version="3.13.14")
    # Tamper with expected_python_version only.
    receipt_path = runtime_root / "macos-arm64" / ".aqa-runtime-ready.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["expected_python_version"] = "3.13.13"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME_PATH),
            "validate-one",
            "--runtime-root",
            str(runtime_root),
            "--requirements",
            str(requirements),
            "--platform",
            "macos-arm64",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0, (
        "validate-one must reject a receipt whose expected_python_version is wrong; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "expected_python_version" in result.stderr, (
        f"expected expected_python_version to be flagged in stderr; got {result.stderr!r}"
    )


def test_validate_one_accepts_receipt_pinned_to_expected_python_version(
    tmp_path: Path,
) -> None:
    runtime_root, requirements = _make_receipt(tmp_path, python_version="3.13.14")
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME_PATH),
            "validate-one",
            "--runtime-root",
            str(runtime_root),
            "--requirements",
            str(requirements),
            "--platform",
            "macos-arm64",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"validate-one must accept a correct receipt; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
