#!/usr/bin/env bash
set -euo pipefail

# Download embedded desktop runtimes from python-build-standalone. Verify the
# pinned 3.13.14+20260623 archives against PLATFORM_DIGESTS before extraction.

PYTHON_VERSION="3.13.14"
BUILD_TAG="20260623"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.."

OUT_DIR="${RUNTIME_DIR:-runtime}"
mkdir -p "$OUT_DIR"
PYTHON_FOR_TOOLS="${PYTHON_FOR_TOOLS:-python3}"
if ! command -v "$PYTHON_FOR_TOOLS" >/dev/null 2>&1; then
  echo "ERROR: python3 is required to validate reusable packaged runtimes." >&2
  exit 1
fi

case "${RUNTIME_FORCE:-0}" in
  0|"") runtime_force=0 ;;
  1)    runtime_force=1 ;;
  *)
    echo "ERROR: RUNTIME_FORCE must be 0 or 1 (got: ${RUNTIME_FORCE})" >&2
    exit 2
    ;;
esac

# Bash 3.2 lacks associative arrays; keep these digests synchronized with
# PLATFORM_DIGESTS in verify_runtime.py.
PLATFORMS=(
  "macos-arm64|https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/cpython-${PYTHON_VERSION}+${BUILD_TAG}-aarch64-apple-darwin-install_only.tar.gz|804c86c8665b18eb0df5070a79d828229018d145baea38a71a5c74c03f9b11d4"
  "macos-x86_64|https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/cpython-${PYTHON_VERSION}+${BUILD_TAG}-x86_64-apple-darwin-install_only.tar.gz|cd0023fb84de358d285c8e116cffd2f433086b943e752955dade521c12e78cab"
  "windows-arm64|https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/cpython-${PYTHON_VERSION}+${BUILD_TAG}-aarch64-pc-windows-msvc-install_only.tar.gz|d425c0fa7fe5e9889760b199c87e45cb84d793639ed63231f9313ffa894cb25a"
  "windows-x86_64|https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/cpython-${PYTHON_VERSION}+${BUILD_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz|646254b53fbac69c1b3c25131c237c9136e9bbed7444123880cea8deaf555e1f"
  "linux-arm64|https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/cpython-${PYTHON_VERSION}+${BUILD_TAG}-aarch64-unknown-linux-gnu-install_only.tar.gz|1199b22c83725a339ebaef36d39476d037fb7267187513090b6cc83bb4579477"
  "linux-x86_64|https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/cpython-${PYTHON_VERSION}+${BUILD_TAG}-x86_64-unknown-linux-gnu-install_only.tar.gz|7fd02919461b368adafea3896ad082f5c4f759816d69681dcc6559bfbcd892af"
)

# macOS ships shasum; Linux distributions commonly ship sha256sum.
sha256_of() {
  local file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    echo "ERROR: neither shasum nor sha256sum is available" >&2
    return 1
  fi
}

validate_existing_runtime() {
  "$PYTHON_FOR_TOOLS" "$SCRIPT_DIR/verify_runtime.py" validate-base \
    --runtime-root "$1" --platform "$2"
}

tmpfile=""
stage_root=""
cleanup_temporary_files() {
  [ -z "$tmpfile" ] || rm -f "$tmpfile"
  [ -z "$stage_root" ] || rm -rf "$stage_root"
}
trap cleanup_temporary_files EXIT HUP INT TERM

if [ -n "${RUNTIME_PLATFORM:-}" ]; then
  case "$RUNTIME_PLATFORM" in
    macos-arm64|macos-x86_64|windows-x86_64|windows-arm64|linux-x86_64|linux-arm64) ;;
    *)
      echo "ERROR: unsupported RUNTIME_PLATFORM: $RUNTIME_PLATFORM" >&2
      exit 2
      ;;
  esac
fi

for entry in "${PLATFORMS[@]}"; do
  if [ -n "${RUNTIME_PLATFORM:-}" ] && [ "${RUNTIME_PLATFORM}" != "${entry%%|*}" ]; then
    continue
  fi
  platform="${entry%%|*}"
  rest="${entry#*|}"
  url="${rest%%|*}"
  expected_sha="${rest##*|}"
  target_dir="$OUT_DIR/$platform"

  if [ "$runtime_force" = "1" ]; then
    echo "[$platform] Refreshing existing runtime because RUNTIME_FORCE=1..."
  elif [ -e "$target_dir" ]; then
    if validate_existing_runtime "$OUT_DIR" "$platform"; then
      echo "[$platform] Existing runtime passed base validation; reusing."
      continue
    fi
    echo "[$platform] Existing runtime is incomplete or stale; downloading a replacement."
  fi

  tmpfile=$(mktemp /tmp/python-standalone.XXXXXX.tar.gz)
  echo "[$platform] Downloading from $url..."
  curl -L -o "$tmpfile" "$url"

  echo "[$platform] Verifying SHA-256..."
  actual_sha="$(sha256_of "$tmpfile")"
  if [ "$actual_sha" != "$expected_sha" ]; then
    echo "ERROR: [$platform] SHA-256 mismatch: expected $expected_sha, got $actual_sha" >&2
    exit 1
  fi

  stage_root=$(mktemp -d "$OUT_DIR/.${platform}.stage.XXXXXX")
  stage_target="$stage_root/$platform"
  mkdir -p "$stage_target"
  echo "[$platform] Extracting..."
  tar -xzf "$tmpfile" -C "$stage_target" --strip-components=1
  rm "$tmpfile"
  tmpfile=""

  if ! validate_existing_runtime "$stage_root" "$platform"; then
    echo "ERROR: [$platform] extracted runtime failed base validation; keeping existing runtime unchanged." >&2
    exit 1
  fi

  if [ -e "$target_dir" ]; then
    backup_dir=$(mktemp -d "$OUT_DIR/.${platform}.backup.XXXXXX")
    rmdir "$backup_dir"
    mv "$target_dir" "$backup_dir"
    if ! mv "$stage_target" "$target_dir"; then
      mv "$backup_dir" "$target_dir" || true
      echo "ERROR: [$platform] failed to replace runtime; restored previous runtime." >&2
      exit 1
    fi
    rm -rf "$backup_dir"
  else
    mv "$stage_target" "$target_dir"
  fi
  rm -rf "$stage_root"
  stage_root=""

  echo "[$platform] Done."
done

echo ""
echo "All runtimes downloaded to $OUT_DIR/"
ls -la "$OUT_DIR"/*/bin/python* "$OUT_DIR"/*/python.exe 2>/dev/null || true
