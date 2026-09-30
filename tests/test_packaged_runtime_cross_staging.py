from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_RUNTIME = PROJECT_ROOT / "packaging" / "runtime" / "verify_runtime.py"
PLATFORM = "windows-x86_64"


def test_stage_one_writes_an_honest_target_receipt(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    executable = runtime_root / PLATFORM / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"placeholder target runtime; must not be executed")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("fastapi==1.0 --hash=sha256:abc\n", encoding="utf-8")
    installer_log = tmp_path / "installer.log"
    installer = tmp_path / "fake-uv"
    installer.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" > "$AQA_TEST_INSTALLER_LOG"\n',
        encoding="utf-8",
    )
    installer.chmod(installer.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME),
            "stage-one",
            "--runtime-root",
            str(runtime_root),
            "--requirements",
            str(requirements),
            "--platform",
            PLATFORM,
            "--installer",
            str(installer),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ | {"AQA_TEST_INSTALLER_LOG": str(installer_log)},
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(
        (runtime_root / PLATFORM / ".aqa-runtime-ready.json").read_text(encoding="utf-8")
    )
    assert receipt == {
        "schema": 2,
        "platform": PLATFORM,
        "build_mode": "cross-staged",
        "python_version": None,
        "expected_python_version": "3.13.14",
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "imports_ok": False,
        "import_check": {
            "success": False,
            "skipped": "target runtime was not executed during cross staging",
        },
    }
    install_call = installer_log.read_text(encoding="utf-8")
    assert "--python-platform x86_64-pc-windows-msvc" in install_call
    assert "--only-binary=:all:" in install_call
    assert "--require-hashes" in install_call

    strict = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME),
            "validate-one",
            "--runtime-root",
            str(runtime_root),
            "--requirements",
            str(requirements),
            "--platform",
            PLATFORM,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert strict.returncode == 1
    assert "requires --allow-cross-staged" in strict.stderr


def test_stage_all_remains_available_for_six_target_app_builds(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    platforms = {
        "macos-arm64": runtime_root / "macos-arm64" / "bin" / "python3",
        "macos-x86_64": runtime_root / "macos-x86_64" / "bin" / "python3",
        "windows-arm64": runtime_root / "windows-arm64" / "python.exe",
        "windows-x86_64": runtime_root / "windows-x86_64" / "python.exe",
        "linux-arm64": runtime_root / "linux-arm64" / "bin" / "python3",
        "linux-x86_64": runtime_root / "linux-x86_64" / "bin" / "python3",
    }
    for executable in platforms.values():
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"placeholder")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("fastapi==1.0 --hash=sha256:abc\n", encoding="utf-8")
    installer_log = tmp_path / "installer.log"
    installer = tmp_path / "fake-uv"
    installer.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$AQA_TEST_INSTALLER_LOG"\n',
        encoding="utf-8",
    )
    installer.chmod(installer.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_RUNTIME),
            "stage-all",
            "--runtime-root",
            str(runtime_root),
            "--requirements",
            str(requirements),
            "--installer",
            str(installer),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ | {"AQA_TEST_INSTALLER_LOG": str(installer_log)},
    )

    assert result.returncode == 0, result.stderr
    assert installer_log.read_text(encoding="utf-8").count("pip install") == 6
    for platform in platforms:
        receipt = json.loads(
            (runtime_root / platform / ".aqa-runtime-ready.json").read_text(encoding="utf-8")
        )
        assert receipt["platform"] == platform
        assert receipt["build_mode"] == "cross-staged"
