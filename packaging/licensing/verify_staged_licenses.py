"""Fail packaging when required license material is missing from a staged payload."""

from __future__ import annotations

import argparse
import email.parser
from pathlib import Path

REQUIRED_NOTICES = (
    "licenses/AQA-LICENSE.txt",
    "licenses/THIRD_PARTY_NOTICES.md",
    "licenses/third-party/APACHE-2.0.txt",
    "licenses/third-party/FRONTEND_DEPENDENCIES.txt",
    "licenses/third-party/LLAMA_CPP-MIT.txt",
    "licenses/third-party/LOGURU-0.7.3-MIT.txt",
    "licenses/third-party/MPL-2.0.txt",
    "licenses/third-party/NVIDIA-CUDA-EULA-2024-01-12.txt",
    "licenses/third-party/NVIDIA-CUDA-EULA-2026-01-26.txt",
    "licenses/third-party/PYTHON_RUNTIME.md",
    "licenses/third-party/RUNTIME_DEPENDENCIES.txt",
    "licenses/third-party/RUST_DEPENDENCIES.html",
    "licenses/third-party/RUST_STDLIB_COPYRIGHT.html",
    "licenses/third-party/RUST_STDLIB_APACHE-2.0.txt",
    "licenses/third-party/RUST_STDLIB_MIT.txt",
    "licenses/third-party/RUST_TOOLCHAIN.json",
    "licenses/third-party/TIKTOKEN-MIT.txt",
    "licenses/third-party/TOMORROW-OFL-1.1.txt",
    "licenses/third-party/python-build-standalone-20260623/LICENSE.cpython.txt",
    "licenses/third-party/python-build-standalone-20260623/LICENSE.openssl-3.txt",
)


def verify(stage_root: Path) -> list[str]:
    errors = [relative for relative in REQUIRED_NOTICES if not (stage_root / relative).is_file()]
    runtime = stage_root / "runtime"
    if not any(path.is_file() for path in runtime.rglob("LICENSE.txt")):
        errors.append("runtime CPython LICENSE.txt")

    for metadata_path in runtime.rglob("*.dist-info/METADATA"):
        metadata = email.parser.Parser().parsestr(metadata_path.read_text(errors="replace"))
        distribution = metadata.get("Name", metadata_path.parent.name)
        license_files = [
            path
            for path in metadata_path.parent.rglob("*")
            if path.is_file()
            and path != metadata_path
            and path.name.lower().startswith(("license", "licence", "copying", "notice"))
        ]
        if not license_files and distribution.lower() != "loguru":
            errors.append(f"runtime license for {distribution}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage_root", type=Path)
    args = parser.parse_args()
    missing = verify(args.stage_root)
    if missing:
        for item in missing:
            print(f"MISSING_LICENSE_MATERIAL: {item}")
        return 1
    print(f"LICENSE_MATERIAL_VALID: {args.stage_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
