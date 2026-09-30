"""Static safety contracts for the Tauri packaging scripts and metadata."""

from __future__ import annotations

import importlib.util
import json
import plistlib
import re
import sys
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_LICENSE_VERIFIER_SPEC = importlib.util.spec_from_file_location(
    "aqa_verify_staged_licenses",
    ROOT / "packaging/licensing/verify_staged_licenses.py",
)
assert _LICENSE_VERIFIER_SPEC is not None and _LICENSE_VERIFIER_SPEC.loader is not None
_LICENSE_VERIFIER = importlib.util.module_from_spec(_LICENSE_VERIFIER_SPEC)
_LICENSE_VERIFIER_SPEC.loader.exec_module(_LICENSE_VERIFIER)

_ARTIFACT_COLLECTOR_SPEC = importlib.util.spec_from_file_location(
    "aqa_collect_desktop_artifacts",
    ROOT / "packaging/desktop/collect_artifacts.py",
)
assert _ARTIFACT_COLLECTOR_SPEC is not None and _ARTIFACT_COLLECTOR_SPEC.loader is not None
_ARTIFACT_COLLECTOR = importlib.util.module_from_spec(_ARTIFACT_COLLECTOR_SPEC)
sys.modules[_ARTIFACT_COLLECTOR_SPEC.name] = _ARTIFACT_COLLECTOR
_ARTIFACT_COLLECTOR_SPEC.loader.exec_module(_ARTIFACT_COLLECTOR)

_DEB_VERSION_SPEC = importlib.util.spec_from_file_location(
    "aqa_normalize_deb_version",
    ROOT / "packaging/desktop/normalize_deb_version.py",
)
assert _DEB_VERSION_SPEC is not None and _DEB_VERSION_SPEC.loader is not None
_DEB_VERSION = importlib.util.module_from_spec(_DEB_VERSION_SPEC)
_DEB_VERSION_SPEC.loader.exec_module(_DEB_VERSION)


def test_desktop_metadata_uses_one_product_identity_and_version() -> None:
    tauri = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text())
    package = json.loads((ROOT / "desktop/package.json").read_text())
    frontend = json.loads((ROOT / "frontend/package.json").read_text())
    desktop_lock = json.loads((ROOT / "desktop/package-lock.json").read_text())
    frontend_lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    openapi = json.loads((ROOT / "openapi/openapi.json").read_text())
    release_info = json.loads((ROOT / "release-info.json").read_text())
    cargo = tomllib.loads((ROOT / "desktop/src-tauri/Cargo.toml").read_text())
    cargo_lock = tomllib.loads((ROOT / "desktop/src-tauri/Cargo.lock").read_text())
    python_version = re.search(r'__version__ = "([^"]+)"', (ROOT / "src/__init__.py").read_text())
    assert tauri["identifier"] == "app.aqa.desktop"
    assert tauri["productName"] == "AQA"
    assert package["name"] == "aqa-desktop"
    assert desktop_lock["name"] == "aqa-desktop"
    assert frontend["name"] == "aqa"
    assert frontend_lock["name"] == "aqa"
    assert cargo["package"]["name"] == "aqa-desktop"
    assert cargo["package"]["description"] == "Augmented Qualitative Analysis"
    assert tauri["bundle"]["shortDescription"] == "Augmented Qualitative Analysis"
    assert tauri["bundle"]["longDescription"] == "Augmented Qualitative Analysis"
    assert tauri["bundle"]["copyright"] == "Copyright (c) 2026 Thomas Krause"
    assert python_version is not None
    versions = {
        tauri["version"],
        package["version"],
        desktop_lock["version"],
        desktop_lock["packages"][""]["version"],
        frontend["version"],
        frontend_lock["version"],
        frontend_lock["packages"][""]["version"],
        release_info["version"],
        openapi["info"]["version"],
        cargo["package"]["version"],
        python_version.group(1),
    }
    desktop_lock_package = next(
        item for item in cargo_lock["package"] if item["name"] == "aqa-desktop"
    )
    versions.add(desktop_lock_package["version"])
    assert versions == {"1.0.0"}
    assert release_info["releaseDate"] == "2026-09-30"
    assert release_info["releaseStatus"] == "stable"
    assert release_info["links"]["githubRepository"] is None
    api_source = (ROOT / "src/service/api_app.py").read_text()
    assert "from src import __version__" in api_source
    assert "version=__version__" in api_source

    macos = tauri["bundle"]["macOS"]
    plist_path = ROOT / "desktop/src-tauri" / macos["infoPlist"]
    with plist_path.open("rb") as plist_file:
        plist = plistlib.load(plist_file)
    numeric_version = tauri["version"].split("-", 1)[0]
    assert macos["bundleVersion"] == numeric_version
    assert plist["CFBundleShortVersionString"] == numeric_version
    assert plist["CFBundleGetInfoString"] == "Augmented Qualitative Analysis"
    assert tauri["bundle"]["windows"]["webviewInstallMode"]["type"] == "offlineInstaller"
    assert tauri["bundle"]["windows"]["nsis"]["installMode"] == "currentUser"
    assert tauri["bundle"]["icon"] == [
        "icons/32x32.png",
        "icons/128x128.png",
        "icons/128x128@2x.png",
        "icons/icon.icns",
        "icons/icon.ico",
    ]
    for icon in tauri["bundle"]["icon"]:
        assert (ROOT / "desktop/src-tauri" / icon).is_file()


def test_desktop_stage_is_allowlisted_and_uses_one_platform_runtime() -> None:
    script = (ROOT / "packaging/desktop/prepare_target.sh").read_text()
    assert "src/desktop_server.py" in script
    assert "src/server_logging.py" in script
    assert 'rsync -a --safe-links "runtime/$TARGET/" "$STAGE_ROOT/runtime/"' in script
    assert "validate-one" in script and '--platform "$TARGET"' in script
    assert "--allow-cross-staged" in script
    assert "validate-all" not in script
    assert "audit-unsafe-symlinks" in script and "--strip" in script
    assert "AQA_DESKTOP_STAGE_ROOT" in script
    for forbidden in (".env", "settings.json", "*.log", "*.db", "*.sqlite"):
        assert forbidden in script


def test_desktop_stage_includes_project_and_third_party_licenses_for_every_target() -> None:
    script = (ROOT / "packaging/desktop/prepare_target.sh").read_text()
    assert 'install -m 0644 LICENSE "$STAGE_ROOT/licenses/AQA-LICENSE.txt"' in script
    assert (
        'install -m 0644 THIRD_PARTY_NOTICES.md "$STAGE_ROOT/licenses/THIRD_PARTY_NOTICES.md"'
    ) in script
    assert (
        'rsync -a --safe-links THIRD_PARTY_LICENSES/ "$STAGE_ROOT/licenses/third-party/"'
    ) in script

    notice_root = ROOT / "THIRD_PARTY_LICENSES"
    for required in (
        "FRONTEND_DEPENDENCIES.txt",
        "LOGURU-0.7.3-MIT.txt",
        "NVIDIA-CUDA-EULA-2024-01-12.txt",
        "NVIDIA-CUDA-EULA-2026-01-26.txt",
        "PYTHON_RUNTIME.md",
        "RUST_DEPENDENCIES.html",
        "RUST_STDLIB_COPYRIGHT.html",
        "RUST_TOOLCHAIN.json",
        "RUNTIME_DEPENDENCIES.txt",
        "TIKTOKEN-MIT.txt",
    ):
        assert (notice_root / required).is_file()

    for target in (
        "macos-arm64",
        "macos-x86_64",
        "windows-arm64",
        "windows-x86_64",
        "linux-arm64",
        "linux-x86_64",
    ):
        assert target in script

    assert 'verify_staged_licenses.py "$STAGE_ROOT"' in script
    assert "generate_rust_notices.py --check" in script

    rust_generator = (ROOT / "packaging/licensing/generate_rust_notices.py").read_text()
    assert 'ROOT / "desktop/src-tauri/Cargo.toml"' in rust_generator
    assert 'CARGO_ABOUT_VERSION = "cargo-about 0.9.2"' in rust_generator
    assert 'recorded.get("cargo_about") != CARGO_ABOUT_VERSION' in rust_generator


def test_staged_license_verifier_detects_an_omitted_notice(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    for relative in _LICENSE_VERIFIER.REQUIRED_NOTICES:
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture")
    runtime = stage / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "LICENSE.txt").write_text("CPython fixture")

    assert _LICENSE_VERIFIER.verify(stage) == []
    omitted = stage / "licenses/THIRD_PARTY_NOTICES.md"
    omitted.unlink()
    assert _LICENSE_VERIFIER.verify(stage) == ["licenses/THIRD_PARTY_NOTICES.md"]


def test_desktop_stage_excludes_test_only_fault_controls() -> None:
    script = (ROOT / "packaging/desktop/prepare_target.sh").read_text()
    assert "tests/" not in script
    assert "AQA_TEST_MODE" not in script
    assert "AQA_E2E_PROVIDER_MODE" not in script
    assert "native_remediation_fixture" not in script
    assert "AQA_TEST_FAILED_SESSION_LIST_REFRESH_ONCE" not in script

    staged_sources = [
        ROOT / "src/api_server.py",
        ROOT / "src/desktop_server.py",
        ROOT / "src/server_logging.py",
        *(ROOT / "src/config").rglob("*.py"),
        *(ROOT / "src/llm").rglob("*.py"),
        *(ROOT / "src/local_ai").rglob("*.py"),
        *(ROOT / "src/prompts").rglob("*.py"),
        *(ROOT / "src/service").rglob("*.py"),
    ]
    production_source = "\n".join(path.read_text() for path in staged_sources)
    for test_only_identifier in (
        "native_remediation_fixture",
        "AQA_TEST_FAILED_SESSION_LIST_REFRESH_ONCE",
        "serve-failed-refresh",
    ):
        assert test_only_identifier not in production_source


def test_native_artifact_names_are_architecture_explicit() -> None:
    script = (ROOT / "packaging/desktop/build_target.sh").read_text()
    collector = (ROOT / "packaging/desktop/collect_artifacts.py").read_text()
    assert "AQA-$VERSION-$OS-${TARGET#macos-}.dmg" in script
    assert 'f"AQA-{version}-windows-{architecture}-setup.exe"' in collector
    assert 'ArtifactSpec("appimage", "*.AppImage", f"{stem}.AppImage")' in collector
    assert 'ArtifactSpec("deb", "*.deb", f"{stem}.deb")' in collector
    assert "validate-one" in script
    assert '--platform "$TARGET"' in script
    assert "--allow-cross-staged" not in script
    assert "AQA_DESKTOP_OUT_DIR" in script
    assert "collect_artifacts.py" in script
    assert 'if [ "$OS" = "linux" ]; then' in script
    assert 'runtime_lib="$PROJECT_ROOT/runtime/$TARGET/lib"' in script
    assert 'LD_LIBRARY_PATH="$runtime_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"' in script
    assert 'normalize_deb_version.py" \\' in script
    normalizer_arguments = '--bundle-dir "$bundle_dir/deb" --app-version "$VERSION"'
    assert normalizer_arguments in script
    assert script.index(normalizer_arguments) < script.rindex("collect_artifacts.py")


def test_prerelease_version_uses_debian_upgrade_ordering() -> None:
    assert _DEB_VERSION.debian_version("1.0.0-beta.1") == "1.0.0~beta.1"
    assert _DEB_VERSION.debian_version("1.0.0") == "1.0.0"
    assert _DEB_VERSION.debian_version("1.0.0-beta.1+build.7") == "1.0.0~beta.1+build.7"
    assert (
        _DEB_VERSION.rewrite_control_version(
            "Package: aqa\nVersion: 1.0.0-beta.1\nArchitecture: arm64\n",
            "1.0.0-beta.1",
        )
        == "Package: aqa\nVersion: 1.0.0~beta.1\nArchitecture: arm64\n"
    )
    with pytest.raises(ValueError, match="invalid semantic version"):
        _DEB_VERSION.debian_version("1.0")


def test_prerelease_artifact_collection_preserves_full_beta_identity(tmp_path: Path) -> None:
    windows_bundle = tmp_path / "windows/bundle"
    windows_output = tmp_path / "windows/output"
    windows_mtime = _write_current_artifact(windows_bundle / "nsis/current.exe")
    assert _ARTIFACT_COLLECTOR.collect(
        "windows-x86_64",
        windows_bundle,
        windows_output,
        "1.0.0-beta.1",
        windows_mtime,
    ) == [windows_output / "AQA-1.0.0-beta.1-windows-x86_64-setup.exe"]

    linux_bundle = tmp_path / "linux/bundle"
    linux_output = tmp_path / "linux/output"
    appimage = linux_bundle / "appimage/current.AppImage"
    deb = linux_bundle / "deb/current.deb"
    linux_mtime = min(_write_current_artifact(appimage), _write_current_artifact(deb))
    assert _ARTIFACT_COLLECTOR.collect(
        "linux-arm64", linux_bundle, linux_output, "1.0.0-beta.1", linux_mtime
    ) == [
        linux_output / "AQA-1.0.0-beta.1-linux-arm64.AppImage",
        linux_output / "AQA-1.0.0-beta.1-linux-arm64.deb",
    ]


def _write_current_artifact(path: Path, content: bytes = b"artifact") -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path.stat().st_mtime_ns


def test_windows_artifact_collection_requires_one_current_nonempty_output(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    output = tmp_path / "output"
    artifact = bundle / "nsis/AQA_0.1.0_x64-setup.exe"
    mtime_ns = _write_current_artifact(artifact)

    collected = _ARTIFACT_COLLECTOR.collect("windows-x86_64", bundle, output, "0.1.0", mtime_ns)
    assert collected == [output / "AQA-0.1.0-windows-x86_64-setup.exe"]
    assert collected[0].read_bytes() == b"artifact"

    for invalid in ("missing", "empty", "stale", "ambiguous"):
        case_bundle = tmp_path / invalid / "bundle"
        case_output = tmp_path / invalid / "output"
        candidate = case_bundle / "nsis/one.exe"
        candidate_mtime = _write_current_artifact(candidate)
        build_started_ns = candidate_mtime
        if invalid == "missing":
            candidate.unlink()
        elif invalid == "empty":
            candidate.write_bytes(b"")
        elif invalid == "stale":
            build_started_ns = time.time_ns() + 1_000_000_000
        else:
            _write_current_artifact(case_bundle / "nsis/two.exe")

        with pytest.raises(_ARTIFACT_COLLECTOR.ArtifactCollectionError):
            _ARTIFACT_COLLECTOR.collect(
                "windows-x86_64", case_bundle, case_output, "0.1.0", build_started_ns
            )
        assert not case_output.exists()


def test_linux_artifact_collection_validates_the_complete_set_before_copying(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    output = tmp_path / "output"
    appimage = bundle / "appimage/AQA.AppImage"
    deb = bundle / "deb/aqa.deb"
    start_ns = min(_write_current_artifact(appimage), _write_current_artifact(deb))

    collected = _ARTIFACT_COLLECTOR.collect("linux-arm64", bundle, output, "0.1.0", start_ns)
    assert collected == [
        output / "AQA-0.1.0-linux-arm64.AppImage",
        output / "AQA-0.1.0-linux-arm64.deb",
    ]

    incomplete_bundle = tmp_path / "incomplete/bundle"
    incomplete_output = tmp_path / "incomplete/output"
    current = _write_current_artifact(incomplete_bundle / "appimage/current.AppImage")
    with pytest.raises(_ARTIFACT_COLLECTOR.ArtifactCollectionError):
        _ARTIFACT_COLLECTOR.collect(
            "linux-x86_64", incomplete_bundle, incomplete_output, "0.1.0", current
        )
    assert not incomplete_output.exists()


def test_artifact_collection_preserves_existing_release_evidence(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    output = tmp_path / "output"
    source = bundle / "nsis/current.exe"
    mtime_ns = _write_current_artifact(source, b"new")
    destination = output / "AQA-0.1.0-windows-arm64-setup.exe"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"preserved")

    with pytest.raises(_ARTIFACT_COLLECTOR.ArtifactCollectionError, match="refusing to overwrite"):
        _ARTIFACT_COLLECTOR.collect("windows-arm64", bundle, output, "0.1.0", mtime_ns)
    assert destination.read_bytes() == b"preserved"


def test_macos_release_destination_collision_is_rejected(tmp_path: Path) -> None:
    destination = tmp_path / "AQA-0.1.0-macos-arm64.dmg"
    destination.write_bytes(b"preserved")
    with pytest.raises(_ARTIFACT_COLLECTOR.ArtifactCollectionError, match="refusing to overwrite"):
        _ARTIFACT_COLLECTOR.ensure_destinations_available([destination])
    assert destination.read_bytes() == b"preserved"


def test_macos_artifact_validation_rejects_stale_or_ambiguous_apps(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    executable = bundle / "macos/AQA.app/Contents/MacOS/aqa-desktop"
    mtime_ns = _write_current_artifact(executable)
    assert _ARTIFACT_COLLECTOR.validate_macos_app(bundle, mtime_ns) == executable

    with pytest.raises(_ARTIFACT_COLLECTOR.ArtifactCollectionError):
        _ARTIFACT_COLLECTOR.validate_macos_app(bundle, time.time_ns() + 1_000_000_000)

    _write_current_artifact(bundle / "macos/Other.app/Contents/MacOS/Other")
    with pytest.raises(_ARTIFACT_COLLECTOR.ArtifactCollectionError):
        _ARTIFACT_COLLECTOR.validate_macos_app(bundle, mtime_ns)


def test_macos_build_uses_app_bundle_and_non_mounting_dmg_creation() -> None:
    script = (ROOT / "packaging/desktop/build_target.sh").read_text()
    assert "macos-arm64) RUST_TARGET=aarch64-apple-darwin; BUNDLES=app; OS=macos" in script
    assert '--bundles "$BUNDLES"' in script
    signing = 'codesign --force --deep --sign - "$dmg_stage/stage/AQA.app"'
    verification = 'codesign --verify --deep --strict --verbose=2 "$dmg_stage/stage/AQA.app"'
    assert signing in script
    assert verification in script
    assert script.index(signing) < script.index('hdiutil create -ov -volname "AQA"')
    assert 'hdiutil create -ov -volname "AQA"' in script
    assert 'ln -s /Applications "$dmg_stage/stage/Applications"' in script
    assert "npm exec -- tauri icon" not in script


def test_windows_release_hides_managed_console_children() -> None:
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text()
    assert '#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]' in source
    assert "command.creation_flags(CREATE_NO_WINDOW)" in source
    assert "const CREATE_NO_WINDOW: u32 = 0x0800_0000" in source
    backend = source.split("fn start_backend(", 1)[1].split("fn monitor_backend(", 1)[0]
    assert "let mut command = Command::new(python);" in backend
    assert "hide_windows_console(&mut command);" in backend
    assert ".stdout(Stdio::piped())" in backend
    assert ".stderr(Stdio::from(log))" in backend
    assert "let mut child = command" in backend
    external = source.split("fn open_external(", 1)[1].split("fn fail(", 1)[0]
    assert 'Command::new("cmd")' in external
    assert "hide_windows_console(&mut command);" in external


def test_native_menu_locale_is_app_owned_while_exports_keep_the_system_dialog() -> None:
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text()
    capability = json.loads((ROOT / "desktop/src-tauri/capabilities/default.json").read_text())
    permission = (ROOT / "desktop/src-tauri/permissions/set_native_menu_locale.toml").read_text()

    assert "fn set_native_menu_locale" in source
    assert "fn build_native_menu" in source
    assert "install_menu(&app, locale)" in source
    assert "set_native_menu_locale" in source.split("tauri::generate_handler!", 1)[1]
    assert "allow-set-native-menu-locale" in capability["permissions"]
    assert 'allow = ["set_native_menu_locale"]' in permission
    assert ".blocking_save_file()" in source
    assert "NSLocale" not in source


def test_desktop_notifications_have_only_the_required_native_permissions() -> None:
    cargo = (ROOT / "desktop/src-tauri/Cargo.toml").read_text()
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text()
    capability = json.loads((ROOT / "desktop/src-tauri/capabilities/default.json").read_text())

    assert 'tauri-plugin-notification = "2.4.0"' in cargo
    assert 'objc2-user-notifications = { version = "0.3.2"' in cargo
    assert 'cfg(not(target_os = "macos"))' in cargo
    assert '#[cfg(not(target_os = "macos"))]' in source
    assert "builder.plugin(tauri_plugin_notification::init())" in source
    notification_permissions = {
        permission
        for permission in capability["permissions"]
        if permission.startswith("notification:")
    }
    assert notification_permissions == set()
    assert "allow-native-notification-permission-state" in capability["permissions"]
    assert "allow-request-native-notification-permission" in capability["permissions"]
    assert "allow-deliver-round-notification" in capability["permissions"]
    assert "UNUserNotificationCenter::currentNotificationCenter" in source
    assert "requestAuthorizationWithOptions_completionHandler" in source
    assert "addNotificationRequest_withCompletionHandler" in source
    assert ".is_focused()" in source
    assert ".is_minimized()" in source
    assert ".is_visible()" in source
    assert '"status": "suppressed"' in source
    assert '"status": "queued"' in source
    assert "round-notification commands" in capability["description"]


def test_generation_sleep_inhibition_has_one_narrow_native_permission() -> None:
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text()
    capability = json.loads((ROOT / "desktop/src-tauri/capabilities/default.json").read_text())
    permission = (
        ROOT / "desktop/src-tauri/permissions/autogenerated/update_generation_sleep_inhibition.toml"
    ).read_text()

    assert "allow-update-generation-sleep-inhibition" in capability["permissions"]
    assert 'allow = ["update_generation_sleep_inhibition"]' in permission
    assert "fn update_generation_sleep_inhibition" in source
    assert "generation sleep-inhibition command" in capability["description"]


def test_native_appearance_has_a_scoped_permission_and_clears_system_override() -> None:
    source = (ROOT / "desktop/src-tauri/src/main.rs").read_text()
    capability = json.loads((ROOT / "desktop/src-tauri/capabilities/default.json").read_text())
    permission = (ROOT / "desktop/src-tauri/permissions/set_native_appearance.toml").read_text()
    assert "allow-set-native-appearance" in capability["permissions"]
    assert 'allow = ["set_native_appearance"]' in permission
    assert "set_native_appearance" in source.split("tauri::generate_handler!", 1)[1]
    assert '"system" => Ok(None)' in source
    assert "window.set_theme(theme)" in source
