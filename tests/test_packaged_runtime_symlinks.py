from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_RUNTIME = PROJECT_ROOT / "packaging" / "runtime" / "verify_runtime.py"

_spec = importlib.util.spec_from_file_location("packaged_verify_runtime", VERIFY_RUNTIME)
assert _spec is not None and _spec.loader is not None
verify_runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_runtime)


def _runtime_with_links(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime = tmp_path / "runtime"
    terms = runtime / "linux-x86_64" / "share" / "terminfo"
    source = terms / "d"
    links = terms / "b"
    source.mkdir(parents=True)
    links.mkdir(parents=True)
    (source / "ddr").write_text("fake", encoding="utf-8")
    unsafe = links / "rebus3180"
    unsafe.symlink_to("../d/ddr")
    safe = links / "regent200"
    safe.symlink_to("xterm")
    return runtime, unsafe, safe


def test_target_escape_classifier_distinguishes_safe_aliases() -> None:
    cases = {
        "../foo": True,
        "..": True,
        "foo/../../bar": True,
        "/etc/passwd": True,
        "xterm": False,
        "subdir/xterm": False,
        "foo/../bar": False,
        "": False,
    }
    for target, expected in cases.items():
        assert verify_runtime._target_escapes_parent(target) is expected


def test_find_unsafe_runtime_symlinks_preserves_safe_aliases(tmp_path: Path) -> None:
    runtime, unsafe, safe = _runtime_with_links(tmp_path)
    absolute = unsafe.parent / "absolute"
    absolute.symlink_to("/etc/passwd")
    found = verify_runtime.find_unsafe_runtime_symlinks(runtime)
    assert found == sorted([unsafe, absolute])
    assert safe not in found


def test_strip_removes_only_unsafe_links_and_is_idempotent(tmp_path: Path) -> None:
    runtime, unsafe, safe = _runtime_with_links(tmp_path)
    target = runtime / "linux-x86_64" / "share" / "terminfo" / "d" / "ddr"
    assert verify_runtime.audit_and_strip_unsafe_symlinks(runtime, strip=True) == 0
    assert not unsafe.exists()
    assert safe.is_symlink()
    assert target.is_file()
    assert verify_runtime.audit_and_strip_unsafe_symlinks(runtime, strip=True) == 0


def test_audit_cli_reports_then_strips_unsafe_links(tmp_path: Path) -> None:
    runtime, unsafe, _safe = _runtime_with_links(tmp_path)
    command = [
        sys.executable,
        str(VERIFY_RUNTIME),
        "audit-unsafe-symlinks",
        "--runtime-root",
        str(runtime),
    ]
    audit = subprocess.run(command, text=True, capture_output=True, check=False)
    assert audit.returncode == 1
    assert unsafe.name in audit.stderr
    stripped = subprocess.run([*command, "--strip"], text=True, capture_output=True, check=False)
    assert stripped.returncode == 0
    assert not unsafe.exists()
    assert subprocess.run(command, text=True, capture_output=True, check=False).returncode == 0
