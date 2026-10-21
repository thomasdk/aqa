from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_RUNTIME = PROJECT_ROOT / "packaging" / "runtime" / "verify_runtime.py"
PLATFORM = "windows-x86_64"

_spec = importlib.util.spec_from_file_location("cross_staging_verify_runtime", VERIFY_RUNTIME)
assert _spec is not None and _spec.loader is not None
verify_runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_runtime)


def _run_stage_cli(
    command: str,
    runtime_root: Path,
    requirements: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    platform: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    install_calls: list[list[str]] = []

    def install(argv: list[str], *, text: bool, check: bool) -> subprocess.CompletedProcess[str]:
        assert argv[0] == sys.executable
        assert text is True
        assert check is False
        install_calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    argv = [
        str(VERIFY_RUNTIME),
        command,
        "--runtime-root",
        str(runtime_root),
        "--requirements",
        str(requirements),
        "--installer",
        sys.executable,
    ]
    if platform is not None:
        argv.extend(["--platform", platform])
    # Keep the real CLI, target paths and receipt writes; replace only the
    # external wheel installer so a Bash executable fixture is unnecessary.
    with monkeypatch.context() as context:
        context.setattr(sys, "argv", argv)
        context.setattr(verify_runtime.subprocess, "run", install)
        returncode = verify_runtime.main()
    captured = capsys.readouterr()
    return subprocess.CompletedProcess(argv, returncode, captured.out, captured.err), install_calls


def test_stage_one_writes_an_honest_target_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime_root = tmp_path / "runtime"
    executable = runtime_root / PLATFORM / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"placeholder target runtime; must not be executed")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("fastapi==1.0 --hash=sha256:abc\n", encoding="utf-8")
    result, install_calls = _run_stage_cli(
        "stage-one", runtime_root, requirements, monkeypatch, capsys, platform=PLATFORM
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
    assert install_calls == [
        [
            sys.executable,
            "pip",
            "install",
            "--target",
            str(runtime_root / PLATFORM / "Lib" / "site-packages"),
            "--exact",
            "--require-hashes",
            "--only-binary=:all:",
            "--python-version",
            "3.13.14",
            "--python-platform",
            "x86_64-pc-windows-msvc",
            "-r",
            str(requirements),
        ]
    ]

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


def test_stage_all_remains_available_for_six_target_app_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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
    result, install_calls = _run_stage_cli(
        "stage-all", runtime_root, requirements, monkeypatch, capsys
    )

    assert result.returncode == 0, result.stderr
    assert len(install_calls) == 6
    assert {call[call.index("--python-platform") + 1] for call in install_calls} == {
        "aarch64-apple-darwin",
        "x86_64-apple-darwin",
        "aarch64-pc-windows-msvc",
        "x86_64-pc-windows-msvc",
        "aarch64-manylinux_2_17",
        "x86_64-manylinux_2_17",
    }
    for platform in platforms:
        receipt = json.loads(
            (runtime_root / platform / ".aqa-runtime-ready.json").read_text(encoding="utf-8")
        )
        assert receipt["platform"] == platform
        assert receipt["build_mode"] == "cross-staged"
