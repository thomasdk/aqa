#!/usr/bin/env python3
"""Validate and collect the exact artifacts emitted by one Tauri build."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


class ArtifactCollectionError(RuntimeError):
    """The build output cannot be identified as one complete current artifact set."""


@dataclass(frozen=True)
class ArtifactSpec:
    bundle_subdir: str
    pattern: str
    output_name: str


def _specs(target: str, version: str) -> tuple[ArtifactSpec, ...]:
    architecture = target.split("-", 1)[1]
    if target.startswith("windows-"):
        return (
            ArtifactSpec(
                "nsis",
                "*.exe",
                f"AQA-{version}-windows-{architecture}-setup.exe",
            ),
        )
    if target.startswith("linux-"):
        stem = f"AQA-{version}-linux-{architecture}"
        return (
            ArtifactSpec("appimage", "*.AppImage", f"{stem}.AppImage"),
            ArtifactSpec("deb", "*.deb", f"{stem}.deb"),
        )
    raise ArtifactCollectionError(f"unsupported collector target: {target}")


def _one_current_nonempty_file(directory: Path, pattern: str, build_started_ns: int) -> Path:
    matches = sorted(path for path in directory.glob(pattern) if path.is_file())
    if len(matches) != 1:
        raise ArtifactCollectionError(
            f"expected exactly one {pattern} in {directory}, found {len(matches)}"
        )
    artifact = matches[0]
    stat = artifact.stat()
    if stat.st_size <= 0:
        raise ArtifactCollectionError(f"artifact is empty: {artifact}")
    if stat.st_mtime_ns < build_started_ns:
        raise ArtifactCollectionError(f"artifact predates the current build: {artifact}")
    return artifact


def validate_macos_app(bundle_dir: Path, build_started_ns: int) -> Path:
    macos_dir = bundle_dir / "macos"
    apps = sorted(path for path in macos_dir.glob("*.app") if path.is_dir())
    expected = macos_dir / "AQA.app"
    if apps != [expected]:
        raise ArtifactCollectionError(
            f"expected exactly AQA.app in {macos_dir}, found {len(apps)} app bundles"
        )
    executable = expected / "Contents/MacOS/aqa-desktop"
    return _one_current_nonempty_file(executable.parent, executable.name, build_started_ns)


def ensure_destinations_available(destinations: list[Path]) -> None:
    collisions = [destination for destination in destinations if destination.exists()]
    if collisions:
        raise ArtifactCollectionError(
            "refusing to overwrite existing release artifact: "
            + ", ".join(str(path) for path in collisions)
        )


def collect(
    target: str,
    bundle_dir: Path,
    out_dir: Path,
    version: str,
    build_started_ns: int,
) -> list[Path]:
    validated = [
        (
            _one_current_nonempty_file(
                bundle_dir / spec.bundle_subdir, spec.pattern, build_started_ns
            ),
            out_dir / spec.output_name,
        )
        for spec in _specs(target, version)
    ]
    ensure_destinations_available([destination for _, destination in validated])
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for source, destination in validated:
        shutil.copy2(source, destination)
        if destination.stat().st_size <= 0:
            raise ArtifactCollectionError(f"collected artifact is empty: {destination}")
        outputs.append(destination)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--build-started-ns", type=int, required=True)
    args = parser.parse_args()

    try:
        if args.target.startswith("macos-"):
            executable = validate_macos_app(args.bundle_dir, args.build_started_ns)
            if args.out_dir is None or args.version is None:
                parser.error("--out-dir and --version are required for macOS")
            architecture = args.target.split("-", 1)[1]
            destination = args.out_dir / f"AQA-{args.version}-macos-{architecture}.dmg"
            ensure_destinations_available([destination])
            print(executable)
        else:
            if args.out_dir is None or args.version is None:
                parser.error("--out-dir and --version are required for artifact collection")
            for output in collect(
                args.target,
                args.bundle_dir,
                args.out_dir,
                args.version,
                args.build_started_ns,
            ):
                print(output)
    except ArtifactCollectionError as error:
        parser.exit(1, f"artifact collection failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
