from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_RUNTIME = PROJECT_ROOT / "packaging" / "runtime" / "verify_runtime.py"
PLATFORM = "linux-x86_64"

_spec = importlib.util.spec_from_file_location("packaged_verify_runtime", VERIFY_RUNTIME)
assert _spec is not None and _spec.loader is not None
verify_runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_runtime)


def _fixture(tmp_path: Path, *, cross_staged: bool = False) -> tuple[Path, Path, Path]:
    runtime_root = tmp_path / "runtime"
    runtime_dir = runtime_root / PLATFORM
    executable = runtime_dir / "bin" / "python3"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture runtime placeholder")
    requirements = tmp_path / "requirements-runtime.txt"
    requirements.write_text("fastapi\n", encoding="utf-8")
    receipt = {
        "schema": 1,
        "platform": PLATFORM,
        "python_version": verify_runtime.EXPECTED_PYTHON_VERSION,
        "expected_python_version": verify_runtime.EXPECTED_PYTHON_VERSION,
        "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
        "imports_ok": True,
        "import_check": {"success": True},
    }
    if cross_staged:
        receipt.update(
            {
                "schema": 2,
                "build_mode": "cross-staged",
                "python_version": None,
                "imports_ok": False,
                "import_check": {
                    "success": False,
                    "skipped": "target runtime was not executed during cross staging",
                },
            }
        )
    receipt_path = runtime_dir / verify_runtime.RECEIPT_NAME
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return runtime_root, requirements, receipt_path


def _validate(
    runtime_root: Path, requirements: Path, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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
            *extra,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_readiness_import_check_does_not_require_a_native_tokenizer() -> None:
    assert "tiktoken" not in verify_runtime.REQUIRED_IMPORTS


def test_validate_one_accepts_a_native_target_without_a_platform_matrix(tmp_path: Path) -> None:
    runtime_root, requirements, _receipt = _fixture(tmp_path)
    assert _validate(runtime_root, requirements).returncode == 0


def test_validate_one_rejects_cross_staging_without_explicit_opt_in(tmp_path: Path) -> None:
    runtime_root, requirements, _receipt = _fixture(tmp_path, cross_staged=True)
    result = _validate(runtime_root, requirements)
    assert result.returncode == 1
    assert "requires --allow-cross-staged" in result.stderr


def test_validate_one_accepts_one_honest_cross_staged_target(tmp_path: Path) -> None:
    runtime_root, requirements, _receipt = _fixture(tmp_path, cross_staged=True)
    assert _validate(runtime_root, requirements, "--allow-cross-staged").returncode == 0


def test_validate_one_rejects_a_forged_cross_staged_receipt(tmp_path: Path) -> None:
    runtime_root, requirements, receipt_path = _fixture(tmp_path, cross_staged=True)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["imports_ok"] = True
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    result = _validate(runtime_root, requirements, "--allow-cross-staged")
    assert result.returncode == 1
    assert "imports_ok" in result.stderr
