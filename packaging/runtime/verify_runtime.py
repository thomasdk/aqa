#!/usr/bin/env python3
"""Verify and prepare embedded Python runtime folders for desktop packages.

This helper intentionally uses only the standard library. The ``check`` command
runs under the target interpreter after dependencies are installed; validation
inspects receipts and paths only, so it is safe on a host that cannot execute a
foreign runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform as platform_module
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_PLATFORMS = (
    "macos-arm64",
    "macos-x86_64",
    "windows-arm64",
    "windows-x86_64",
    "linux-arm64",
    "linux-x86_64",
)
FETCH_PLATFORMS = (
    "macos-arm64",
    "macos-x86_64",
    "windows-arm64",
    "windows-x86_64",
    "linux-arm64",
    "linux-x86_64",
)
# Digests for the upstream 3.13.14+20260623 install_only tarballs. Keep these
# synchronized with fetch_runtimes.sh.
PLATFORM_DIGESTS: dict[str, str] = {
    "macos-arm64": "804c86c8665b18eb0df5070a79d828229018d145baea38a71a5c74c03f9b11d4",
    "macos-x86_64": "cd0023fb84de358d285c8e116cffd2f433086b943e752955dade521c12e78cab",
    "windows-arm64": "d425c0fa7fe5e9889760b199c87e45cb84d793639ed63231f9313ffa894cb25a",
    "windows-x86_64": "646254b53fbac69c1b3c25131c237c9136e9bbed7444123880cea8deaf555e1f",
    "linux-arm64": "1199b22c83725a339ebaef36d39476d037fb7267187513090b6cc83bb4579477",
    "linux-x86_64": "7fd02919461b368adafea3896ad082f5c4f759816d69681dcc6559bfbcd892af",
}
EXPECTED_PYTHON_VERSION = "3.13.14"
RECEIPT_NAME = ".aqa-runtime-ready.json"
CROSS_STAGING_PLATFORMS = {
    "macos-arm64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
    "windows-arm64": "aarch64-pc-windows-msvc",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "linux-arm64": "aarch64-manylinux_2_17",
    "linux-x86_64": "x86_64-manylinux_2_17",
}
REQUIRED_IMPORTS = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic_core",
    "pydantic_settings",
    "loguru",
    "dotenv",
    "requests",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="check imports and write a readiness receipt")
    check.add_argument("--platform", required=True, choices=REQUIRED_PLATFORMS)
    check.add_argument("--runtime-dir", type=Path, required=True)
    check.add_argument("--requirements", type=Path, required=True)

    base = subparsers.add_parser(
        "validate-base",
        help="validate one reusable CPython runtime without executing it",
    )
    base.add_argument("--runtime-root", type=Path, required=True)
    base.add_argument("--platform", required=True, choices=REQUIRED_PLATFORMS)

    validate_one = subparsers.add_parser("validate-one", help="validate one target runtime receipt")
    validate_one.add_argument("--runtime-root", type=Path, required=True)
    validate_one.add_argument("--requirements", type=Path, required=True)
    validate_one.add_argument("--platform", required=True, choices=REQUIRED_PLATFORMS)
    validate_one.add_argument(
        "--allow-cross-staged",
        action="store_true",
        help="accept an honest cross-staged receipt whose target imports have not yet run",
    )

    stage = subparsers.add_parser(
        "stage-one",
        help="cross-install wheel-only dependencies for one target without executing target Python",
    )
    stage.add_argument("--runtime-root", type=Path, required=True)
    stage.add_argument("--requirements", type=Path, required=True)
    stage.add_argument("--platform", required=True, choices=REQUIRED_PLATFORMS)
    stage.add_argument("--installer", default="uv", help="host installer executable (default: uv)")

    stage_all = subparsers.add_parser(
        "stage-all",
        help="cross-install wheel-only dependencies for every desktop target",
    )
    stage_all.add_argument("--runtime-root", type=Path, required=True)
    stage_all.add_argument("--requirements", type=Path, required=True)
    stage_all.add_argument(
        "--installer", default="uv", help="host installer executable (default: uv)"
    )

    audit = subparsers.add_parser(
        "audit-unsafe-symlinks",
        help=(
            "scan a runtime root for symlinks whose target escapes the link's own "
            "directory via '..' segments; with --strip, also delete them"
        ),
    )
    audit.add_argument(
        "--runtime-root",
        type=Path,
        required=True,
        help="root directory containing per-platform runtime trees",
    )
    audit.add_argument(
        "--strip",
        action="store_true",
        help="delete offending symlinks (the link itself, not its target) instead of only reporting them",
    )
    return parser


def _requirements_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as requirements_file:
        for chunk in iter(lambda: requirements_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _python_path(runtime_dir: Path, runtime_platform: str) -> Path:
    # python-build-standalone uses a flat Windows layout and bin/ on POSIX.
    if runtime_platform.startswith("windows-"):
        return runtime_dir / "python.exe"
    return runtime_dir / "bin" / "python3"


def _site_packages_path(runtime_dir: Path, runtime_platform: str) -> Path:
    """Return target site-packages without running a foreign interpreter."""
    if runtime_platform.startswith("windows-"):
        return runtime_dir / "Lib" / "site-packages"
    major_minor = EXPECTED_PYTHON_VERSION.rsplit(".", 1)[0]
    return runtime_dir / "lib" / f"python{major_minor}" / "site-packages"


def validate_base_runtime(runtime_root: Path, runtime_platform: str) -> bool:
    """Validate reusable CPython files without executing a foreign runtime.

    ``stage-one`` replaces site-packages, so only the executable, standard
    library, and version header are checked here.
    """
    runtime_dir = runtime_root / runtime_platform
    if not runtime_dir.is_dir():
        print(f"ERROR: missing runtime directory: {runtime_platform}", file=sys.stderr)
        return False

    major_minor = EXPECTED_PYTHON_VERSION.rsplit(".", 1)[0]
    if runtime_platform.startswith("windows-"):
        required_files = (
            Path("python.exe"),
            Path("python313.dll"),
            Path("Lib") / "os.py",
            Path("Lib") / "encodings" / "__init__.py",
            Path("include") / "patchlevel.h",
        )
        required_dirs = (Path("DLLs"),)
        header_path = runtime_dir / "include" / "patchlevel.h"
    else:
        required_files = (
            Path("bin") / "python3",
            Path("bin") / f"python{major_minor}",
            Path("lib") / f"python{major_minor}" / "os.py",
            Path("lib") / f"python{major_minor}" / "encodings" / "__init__.py",
            Path("include") / f"python{major_minor}" / "patchlevel.h",
        )
        required_dirs = ()
        header_path = runtime_dir / "include" / f"python{major_minor}" / "patchlevel.h"

    invalid_parts: list[str] = []
    for relative_path in required_files:
        if not (runtime_dir / relative_path).is_file():
            invalid_parts.append(f"missing file {relative_path}")
    for relative_path in required_dirs:
        if not (runtime_dir / relative_path).is_dir():
            invalid_parts.append(f"missing directory {relative_path}")
    if invalid_parts:
        print(
            f"ERROR: invalid base runtime {runtime_platform}: " + ", ".join(invalid_parts),
            file=sys.stderr,
        )
        return False

    try:
        header = header_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print(
            f"ERROR: unreadable version header for {runtime_platform}: {header_path}",
            file=sys.stderr,
        )
        return False
    match = re.search(r'^#define\s+PY_VERSION\s+"([^"]+)"', header, flags=re.MULTILINE)
    actual_version = match.group(1) if match else None
    if actual_version != EXPECTED_PYTHON_VERSION:
        print(
            f"ERROR: invalid base runtime version for {runtime_platform}: "
            f"expected {EXPECTED_PYTHON_VERSION}, got {actual_version or 'missing'}",
            file=sys.stderr,
        )
        return False

    print(f"BASE_RUNTIME_VALID: {runtime_platform}")
    return True


def _load_receipt(path: Path, runtime_platform: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(f"ERROR: invalid readiness receipt: {runtime_platform}", file=sys.stderr)
        return None
    if not isinstance(value, dict):
        print(f"ERROR: invalid readiness receipt: {runtime_platform}", file=sys.stderr)
        return None
    return value


def _cross_staged_receipt_errors(
    receipt: dict[str, Any], requirements_hash: str, runtime_platform: str
) -> list[str]:
    expected = {
        "schema": 2,
        "platform": runtime_platform,
        "python_version": None,
        "expected_python_version": EXPECTED_PYTHON_VERSION,
        "requirements_sha256": requirements_hash,
        "imports_ok": False,
    }
    invalid = [name for name, value in expected.items() if receipt.get(name) != value]
    import_check = receipt.get("import_check")
    if not isinstance(import_check, dict) or import_check.get("success") is not False:
        invalid.append("import_check")
    elif import_check.get("skipped") != "target runtime was not executed during cross staging":
        invalid.append("import_check.skipped")
    return invalid


def _native_receipt_errors(
    receipt: dict[str, Any], requirements_hash: str, runtime_platform: str
) -> list[str]:
    expected = {
        "schema": 1,
        "platform": runtime_platform,
        "expected_python_version": EXPECTED_PYTHON_VERSION,
        "requirements_sha256": requirements_hash,
        "imports_ok": True,
    }
    invalid = [name for name, value in expected.items() if receipt.get(name) != value]
    version = receipt.get("python_version")
    if not isinstance(version, str) or version != EXPECTED_PYTHON_VERSION:
        invalid.append("python_version")
    import_check = receipt.get("import_check")
    if not isinstance(import_check, dict) or import_check.get("success") is not True:
        invalid.append("import_check")
    return invalid


def _validated_receipt(
    receipt: dict[str, Any], requirements_hash: str, runtime_platform: str, allow_cross_staged: bool
) -> dict[str, Any] | None:
    cross_staged = receipt.get("build_mode") == "cross-staged"
    invalid = (
        _cross_staged_receipt_errors(receipt, requirements_hash, runtime_platform)
        if cross_staged
        else _native_receipt_errors(receipt, requirements_hash, runtime_platform)
    )
    if invalid:
        kind = "cross-staged " if cross_staged else ""
        print(
            f"ERROR: invalid {kind}receipt fields for {runtime_platform}: " + ", ".join(invalid),
            file=sys.stderr,
        )
        return None
    if cross_staged and not allow_cross_staged:
        print(
            f"ERROR: cross-staged receipt for {runtime_platform} requires --allow-cross-staged",
            file=sys.stderr,
        )
        return None
    return receipt


def _validate_one(
    runtime_root: Path,
    requirements_hash: str,
    runtime_platform: str,
    *,
    allow_cross_staged: bool,
) -> dict[str, Any] | None:
    runtime_dir = runtime_root / runtime_platform
    if not runtime_dir.is_dir():
        print(f"ERROR: missing runtime directory: {runtime_platform}", file=sys.stderr)
        return None

    python_path = _python_path(runtime_dir, runtime_platform)
    if not python_path.is_file():
        print(f"ERROR: missing runtime executable: {runtime_platform}", file=sys.stderr)
        return None

    receipt_path = runtime_dir / RECEIPT_NAME
    if not receipt_path.is_file():
        print(f"ERROR: missing readiness receipt: {runtime_platform}", file=sys.stderr)
        return None

    receipt = _load_receipt(receipt_path, runtime_platform)
    if receipt is None:
        return None

    return _validated_receipt(receipt, requirements_hash, runtime_platform, allow_cross_staged)


def validate_one(
    runtime_root: Path,
    requirements: Path,
    runtime_platform: str,
    *,
    allow_cross_staged: bool = False,
) -> bool:
    """Validate one target receipt; cross-staged receipts require explicit opt-in."""
    if not requirements.is_file():
        print("ERROR: missing requirements file: requirements-runtime.txt", file=sys.stderr)
        return False
    return (
        _validate_one(
            runtime_root,
            _requirements_sha256(requirements),
            runtime_platform,
            allow_cross_staged=allow_cross_staged,
        )
        is not None
    )


def check_and_write_receipt(runtime_platform: str, runtime_dir: Path, requirements: Path) -> int:
    if not requirements.is_file():
        print("ERROR: missing requirements file: requirements-runtime.txt", file=sys.stderr)
        return 1
    if not runtime_dir.is_dir():
        print(f"ERROR: missing runtime directory: {runtime_platform}", file=sys.stderr)
        return 1

    actual_python_version = platform_module.python_version()
    if actual_python_version != EXPECTED_PYTHON_VERSION:
        print(
            f"ERROR: packaged runtime is pinned to {EXPECTED_PYTHON_VERSION} "
            f"but interpreter reports {actual_python_version}",
            file=sys.stderr,
        )
        return 1

    for module_name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception:
            print(f"ERROR: import check failed: {module_name}", file=sys.stderr)
            return 1

    receipt = {
        "schema": 1,
        "platform": runtime_platform,
        "python_version": actual_python_version,
        "expected_python_version": EXPECTED_PYTHON_VERSION,
        "requirements_sha256": _requirements_sha256(requirements),
        "imports_ok": True,
        "import_check": {"success": True, "modules": list(REQUIRED_IMPORTS)},
    }
    receipt_path = runtime_dir / RECEIPT_NAME
    temporary_path = receipt_path.with_name(receipt_path.name + ".tmp")
    temporary_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_path, receipt_path)
    print(f"READY: {runtime_platform}")
    return 0


def stage_cross_platform_runtime(
    runtime_root: Path, requirements: Path, runtime_platform: str, installer: str
) -> int:
    """Install wheels for one target without running a foreign Python binary.

    The resulting schema-2 receipts are intentionally not native readiness
    receipts: their ``imports_ok`` field is false until a target host runs the
    normal ``check`` command through ``install_deps.sh``.
    """
    if not requirements.is_file():
        print("ERROR: missing requirements file: requirements-runtime.txt", file=sys.stderr)
        return 1
    installer_path = shutil.which(installer) if not os.path.isabs(installer) else installer
    if installer_path is None or not Path(installer_path).is_file():
        print(f"ERROR: cross-stage installer not found: {installer}", file=sys.stderr)
        return 1
    requirements_hash = _requirements_sha256(requirements)

    runtime_dir = runtime_root / runtime_platform
    if not runtime_dir.is_dir():
        print(f"ERROR: missing runtime directory: {runtime_platform}", file=sys.stderr)
        return 1
    if not _python_path(runtime_dir, runtime_platform).is_file():
        print(f"ERROR: missing runtime executable: {runtime_platform}", file=sys.stderr)
        return 1

    site_packages = _site_packages_path(runtime_dir, runtime_platform)
    shutil.rmtree(site_packages, ignore_errors=True)
    site_packages.mkdir(parents=True, exist_ok=True)
    command = [
        installer_path,
        "pip",
        "install",
        "--target",
        str(site_packages),
        "--exact",
        "--require-hashes",
        "--only-binary=:all:",
        "--python-version",
        EXPECTED_PYTHON_VERSION,
        "--python-platform",
        CROSS_STAGING_PLATFORMS[runtime_platform],
        "-r",
        str(requirements),
    ]
    result = subprocess.run(command, text=True, check=False)
    if result.returncode != 0:
        print(f"ERROR: cross-stage install failed: {runtime_platform}", file=sys.stderr)
        return result.returncode

    receipt = {
        "schema": 2,
        "platform": runtime_platform,
        "build_mode": "cross-staged",
        "python_version": None,
        "expected_python_version": EXPECTED_PYTHON_VERSION,
        "requirements_sha256": requirements_hash,
        "imports_ok": False,
        "import_check": {
            "success": False,
            "skipped": "target runtime was not executed during cross staging",
        },
    }
    (runtime_dir / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"STAGED: {runtime_platform}")
    return 0


def stage_all_cross_platform_runtimes(
    runtime_root: Path, requirements: Path, installer: str
) -> int:
    """Cross-stage every supported desktop target for an all-platform build run."""
    for runtime_platform in REQUIRED_PLATFORMS:
        result = stage_cross_platform_runtime(
            runtime_root, requirements, runtime_platform, installer
        )
        if result != 0:
            return result
    return 0


def _target_escapes_parent(target: str) -> bool:
    """Return whether a normalized symlink target is absolute or parent-relative.

    Same-directory aliases remain valid because CPython's terminfo tree relies
    on them and package extractors can recreate them safely.
    """
    if not target:
        # An empty target is a broken link, not an unsafe-escape link.
        return False
    normalised = os.path.normpath(target)
    if os.path.isabs(normalised):
        return True
    if normalised == ".." or normalised.startswith(".." + os.sep):
        return True
    return False


def find_unsafe_runtime_symlinks(runtime_root: Path) -> list[Path]:
    """Return unsafe symlinks in stable order, skipping unreadable links."""
    if not runtime_root.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(runtime_root, followlinks=False):
        # os.walk keeps symlinked directories in ``dirnames`` even with
        # ``followlinks=False``. Audit both collections so an unsafe
        # directory link cannot bypass the same policy as unsafe file links.
        for entry_name in [*dirnames, *filenames]:
            link_path = Path(dirpath) / entry_name
            if not link_path.is_symlink():
                continue
            try:
                target = os.readlink(link_path)
            except OSError:
                continue
            if _target_escapes_parent(target):
                found.append(link_path)
    found.sort()
    return found


def audit_and_strip_unsafe_symlinks(runtime_root: Path, *, strip: bool) -> int:
    """Report unsafe symlinks, optionally removing them; return 0 only if none remain."""
    offending = find_unsafe_runtime_symlinks(runtime_root)
    if not offending:
        print(f"UNSAFE_SYMLINKS: 0 in {runtime_root}")
        return 0
    for link_path in offending:
        try:
            target = os.readlink(link_path)
        except OSError:
            target = "<unreadable>"
        if strip:
            try:
                link_path.unlink()
                print(
                    f"STRIP_UNSAFE_SYMLINK: {link_path} -> {target}",
                    file=sys.stderr,
                )
            except OSError as exc:
                print(
                    f"ERROR: failed to strip unsafe symlink {link_path} -> {target}: {exc}",
                    file=sys.stderr,
                )
                return 1
        else:
            print(
                f"UNSAFE_SYMLINK: {link_path} -> {target}",
                file=sys.stderr,
            )
    return 0 if strip else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check":
        return check_and_write_receipt(args.platform, args.runtime_dir, args.requirements)
    if args.command == "validate-base":
        return 0 if validate_base_runtime(args.runtime_root, args.platform) else 1
    if args.command == "validate-one":
        return (
            0
            if validate_one(
                args.runtime_root,
                args.requirements,
                args.platform,
                allow_cross_staged=args.allow_cross_staged,
            )
            else 1
        )
    if args.command == "stage-one":
        return stage_cross_platform_runtime(
            args.runtime_root, args.requirements, args.platform, args.installer
        )
    if args.command == "stage-all":
        return stage_all_cross_platform_runtimes(
            args.runtime_root, args.requirements, args.installer
        )
    if args.command == "audit-unsafe-symlinks":
        return audit_and_strip_unsafe_symlinks(args.runtime_root, strip=args.strip)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
