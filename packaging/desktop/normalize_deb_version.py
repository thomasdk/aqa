#!/usr/bin/env python3
"""Give prerelease Debian packages upgrade-safe version ordering."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SEMVER_PATTERN = re.compile(
    r"^(?P<core>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


def debian_version(app_version: str) -> str:
    match = SEMVER_PATTERN.fullmatch(app_version)
    if match is None:
        raise ValueError(f"invalid semantic version: {app_version}")
    version = f"{match.group('core')}.{match.group('minor')}.{match.group('patch')}"
    if prerelease := match.group("prerelease"):
        version += f"~{prerelease}"
    if build := match.group("build"):
        version += f"+{build}"
    return version


def rewrite_control_version(control: str, app_version: str) -> str:
    expected = f"Version: {app_version}"
    replacement = f"Version: {debian_version(app_version)}"
    if control.count(expected) != 1:
        raise ValueError(f"expected exactly one {expected!r} entry in Debian control metadata")
    return control.replace(expected, replacement)


def normalize_package(package: Path, app_version: str) -> None:
    expected_version = debian_version(app_version)
    if expected_version == app_version:
        return
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        raise RuntimeError("dpkg-deb is required to normalize prerelease package metadata")
    with tempfile.TemporaryDirectory(prefix="aqa-deb-version-") as temporary:
        root = Path(temporary) / "root"
        rebuilt = Path(temporary) / package.name
        subprocess.run([dpkg_deb, "--raw-extract", str(package), str(root)], check=True)
        control_path = root / "DEBIAN/control"
        control = control_path.read_text(encoding="utf-8")
        control_path.write_text(rewrite_control_version(control, app_version), encoding="utf-8")
        subprocess.run(
            [dpkg_deb, "--build", "--root-owner-group", str(root), str(rebuilt)], check=True
        )
        actual_version = subprocess.run(
            [dpkg_deb, "--field", str(rebuilt), "Version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual_version != expected_version:
            raise RuntimeError(
                f"rebuilt Debian version is {actual_version!r}, expected {expected_version!r}"
            )
        os.replace(rebuilt, package)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--app-version", required=True)
    args = parser.parse_args()
    packages = sorted(args.bundle_dir.glob("*.deb"))
    if len(packages) != 1:
        parser.error(
            f"expected exactly one Debian package in {args.bundle_dir}, found {len(packages)}"
        )
    normalize_package(packages[0], args.app_version)
    print(f"Debian package version: {debian_version(args.app_version)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
