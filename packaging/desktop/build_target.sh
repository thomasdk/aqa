#!/usr/bin/env bash
# Build a native Tauri package, then copy artifacts to architecture-explicit
# release names. This must run on the native target OS/architecture (or a
# properly provisioned native CI runner); cross-staging alone is not execution.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"
TARGET="${1:?usage: build_target.sh <target>}"

case "$TARGET" in
  macos-arm64) RUST_TARGET=aarch64-apple-darwin; BUNDLES=app; OS=macos ;;
  macos-x86_64) RUST_TARGET=x86_64-apple-darwin; BUNDLES=app; OS=macos ;;
  windows-x86_64) RUST_TARGET=x86_64-pc-windows-msvc; BUNDLES=nsis; OS=windows ;;
  windows-arm64) RUST_TARGET=aarch64-pc-windows-msvc; BUNDLES=nsis; OS=windows ;;
  linux-x86_64) RUST_TARGET=x86_64-unknown-linux-gnu; BUNDLES=appimage,deb; OS=linux ;;
  linux-arm64) RUST_TARGET=aarch64-unknown-linux-gnu; BUNDLES=appimage,deb; OS=linux ;;
  *) echo "Unsupported desktop target: $TARGET" >&2; exit 2 ;;
esac

# A package is native-verified only when this exact target runtime has run
# its import checks. A cross-staged receipt is useful for structural cross-builds
# but must not pass this strict gate or be presented as native evidence.
python3 packaging/runtime/verify_runtime.py validate-one \
  --runtime-root runtime --requirements requirements-runtime.txt --platform "$TARGET"

"$SCRIPT_DIR/prepare_target.sh" "$TARGET"
# Versioned icon assets are deliberately not regenerated here: `tauri icon`
# embeds nondeterministic metadata in icon.icns and would leave a clean source
# checkout modified after every release build.
BUILD_STARTED_NS="$(python3 -c 'import time; print(time.time_ns())')"
# python-build-standalone keeps optional extension dependencies such as Tcl
# beside the embedded interpreter. linuxdeploy inspects every staged ELF file
# through the host loader, so expose that directory while it resolves the
# package closure; the path is not persisted as an application runtime setting.
if [ "$OS" = "linux" ]; then
  runtime_lib="$PROJECT_ROOT/runtime/$TARGET/lib"
  export LD_LIBRARY_PATH="$runtime_lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
(cd desktop && CI="${CI:-true}" npm exec -- tauri build --target "$RUST_TARGET" --bundles "$BUNDLES")

OUT_DIR="${AQA_DESKTOP_OUT_DIR:-$PROJECT_ROOT/dist/desktop}"
mkdir -p "$OUT_DIR"
VERSION="$(python3 -c 'from src import __version__; print(__version__)')"
bundle_dir="$PROJECT_ROOT/desktop/src-tauri/target/$RUST_TARGET/release/bundle"
if [ "$OS" = "linux" ]; then
  python3 "$SCRIPT_DIR/normalize_deb_version.py" \
    --bundle-dir "$bundle_dir/deb" --app-version "$VERSION"
fi
case "$OS" in
  macos)
    python3 "$SCRIPT_DIR/collect_artifacts.py" \
      --target "$TARGET" --bundle-dir "$bundle_dir" --out-dir "$OUT_DIR" \
      --version "$VERSION" \
      --build-started-ns "$BUILD_STARTED_NS"
    output="$OUT_DIR/AQA-$VERSION-$OS-${TARGET#macos-}.dmg"
    # Avoid Tauri's create-dmg wrapper, which mounts a writable image and can
    # fail in constrained or headless macOS release environments. A simple
    # read-only image containing the app and Applications link keeps the normal
    # drag-to-Applications install path without requiring Finder automation.
    dmg_stage="$(mktemp -d)"
    trap 'rm -rf "$dmg_stage"' EXIT
    mkdir -p "$dmg_stage/stage"
    cp -R "$bundle_dir/macos/AQA.app" "$dmg_stage/stage/"
    ln -s /Applications "$dmg_stage/stage/Applications"
    # Seal the complete bundle even when no Developer ID identity is available.
    # This provides internal integrity verification only; it does not establish
    # publisher trust or replace Developer ID signing and notarization.
    codesign --force --deep --sign - "$dmg_stage/stage/AQA.app"
    codesign --verify --deep --strict --verbose=2 "$dmg_stage/stage/AQA.app"
    hdiutil create -ov -volname "AQA" -srcfolder "$dmg_stage/stage" -format UDZO "$dmg_stage/AQA.dmg"
    mv "$dmg_stage/AQA.dmg" "$output"
    [ -s "$output" ] || { echo "Collected artifact is empty: $output" >&2; exit 1; }
    trap - EXIT
    rm -rf "$dmg_stage"
    ;;
  windows|linux)
    python3 "$SCRIPT_DIR/collect_artifacts.py" \
      --target "$TARGET" --bundle-dir "$bundle_dir" --out-dir "$OUT_DIR" \
      --version "$VERSION" --build-started-ns "$BUILD_STARTED_NS"
    ;;
esac
echo "Native artifacts copied to $OUT_DIR"
