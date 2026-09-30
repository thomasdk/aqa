"""Generate and validate Rust dependency and standard-library notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTICE_ROOT = ROOT / "THIRD_PARTY_LICENSES"
RECORD_PATH = NOTICE_ROOT / "RUST_TOOLCHAIN.json"
CARGO_ABOUT_VERSION = "cargo-about 0.9.2"
TRACKED_INPUTS = (
    ROOT / "desktop/src-tauri/Cargo.lock",
    ROOT / "desktop/src-tauri/Cargo.toml",
    ROOT / "desktop/src-tauri/about.toml",
    ROOT / "desktop/src-tauri/about.hbs",
)
GENERATED_FILES = (
    NOTICE_ROOT / "RUST_DEPENDENCIES.html",
    NOTICE_ROOT / "RUST_STDLIB_COPYRIGHT.html",
    NOTICE_ROOT / "RUST_STDLIB_APACHE-2.0.txt",
    NOTICE_ROOT / "RUST_STDLIB_MIT.txt",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rustc_identity() -> dict[str, str]:
    output = subprocess.check_output(["rustc", "--version", "--verbose"], text=True).splitlines()
    fields = dict(line.split(": ", 1) for line in output[1:] if ": " in line)
    return {
        "release": fields["release"],
        "commit_hash": fields["commit-hash"],
        "commit_date": fields["commit-date"],
        "llvm_version": fields["LLVM version"],
    }


def _sysroot() -> Path:
    return Path(subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip())


def _cargo_about_version() -> str:
    return subprocess.check_output(["cargo", "about", "--version"], text=True).strip()


def _record(identity: dict[str, str]) -> dict[str, object]:
    commit = identity["commit_hash"]
    return {
        "schema": 1,
        "rustc": identity,
        "cargo_about": _cargo_about_version(),
        "sources": {
            "standard_library": f"https://github.com/rust-lang/rust/tree/{commit}/library",
            "copyright": f"https://github.com/rust-lang/rust/blob/{commit}/COPYRIGHT",
            "copyright_generator": (
                f"https://github.com/rust-lang/rust/tree/{commit}/src/tools/generate-copyright"
            ),
            "apache_2_0": f"https://github.com/rust-lang/rust/blob/{commit}/LICENSE-APACHE",
            "mit": f"https://github.com/rust-lang/rust/blob/{commit}/LICENSE-MIT",
        },
        "inputs": {path.relative_to(ROOT).as_posix(): _sha256(path) for path in TRACKED_INPUTS},
        "outputs": {path.relative_to(ROOT).as_posix(): _sha256(path) for path in GENERATED_FILES},
    }


def generate() -> None:
    identity = _rustc_identity()
    commit = identity["commit_hash"]
    installed_cargo_about = _cargo_about_version()
    if installed_cargo_about != CARGO_ABOUT_VERSION:
        raise RuntimeError(f"expected {CARGO_ABOUT_VERSION}, found {installed_cargo_about}")
    subprocess.run(
        [
            "cargo",
            "about",
            "generate",
            "--locked",
            "--fail",
            "--manifest-path",
            "desktop/src-tauri/Cargo.toml",
            "--config",
            "desktop/src-tauri/about.toml",
            "--output-file",
            str(GENERATED_FILES[0]),
            "desktop/src-tauri/about.hbs",
        ],
        cwd=ROOT,
        check=True,
    )
    GENERATED_FILES[0].write_bytes(GENERATED_FILES[0].read_bytes().replace(b"\r\n", b"\n"))
    shutil.copyfile(_sysroot() / "share/doc/rust/COPYRIGHT-library.html", GENERATED_FILES[1])
    for upstream_name, destination in (
        ("LICENSE-APACHE", GENERATED_FILES[2]),
        ("LICENSE-MIT", GENERATED_FILES[3]),
    ):
        url = f"https://raw.githubusercontent.com/rust-lang/rust/{commit}/{upstream_name}"
        with urllib.request.urlopen(url) as response:  # noqa: S310 - fixed official host
            destination.write_bytes(response.read())
    RECORD_PATH.write_text(json.dumps(_record(identity), indent=2, sort_keys=True) + "\n")


def verify() -> list[str]:
    if not RECORD_PATH.is_file():
        return [f"missing {RECORD_PATH.relative_to(ROOT)}"]
    recorded = json.loads(RECORD_PATH.read_text())
    current_identity = _rustc_identity()
    errors = []
    if recorded.get("rustc") != current_identity:
        errors.append(
            "Rust toolchain changed; regenerate notices with "
            "packaging/licensing/generate_rust_notices.py"
        )
    if recorded.get("cargo_about") != CARGO_ABOUT_VERSION:
        errors.append(
            "cargo-about changed; regenerate notices with "
            "packaging/licensing/generate_rust_notices.py"
        )
    for group, paths in (("inputs", TRACKED_INPUTS), ("outputs", GENERATED_FILES)):
        hashes = recorded.get(group, {})
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            if not path.is_file() or hashes.get(relative) != _sha256(path):
                errors.append(f"Rust notice {group[:-1]} changed: {relative}")
    copyright_path = _sysroot() / "share/doc/rust/COPYRIGHT-library.html"
    if not copyright_path.is_file() or _sha256(copyright_path) != _sha256(GENERATED_FILES[1]):
        errors.append("Rust standard-library copyright does not match the active toolchain")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        errors = verify()
        for error in errors:
            print(f"STALE_RUST_NOTICE: {error}")
        if errors:
            return 1
        print(f"RUST_NOTICES_VALID: rustc {_rustc_identity()['release']}")
        return 0
    generate()
    print(f"RUST_NOTICES_GENERATED: rustc {_rustc_identity()['release']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
