#!/usr/bin/env bash
set -euo pipefail

# Install dependencies into exactly one native packaged Python runtime.
# RUNTIME_PLATFORM is deliberately required: foreign Python interpreters must
# never be probed or executed from this script.

unset PYTHONPATH

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../.."
VERIFY_SCRIPT="$SCRIPT_DIR/verify_runtime.py"
RUNTIME_ROOT="${RUNTIME_DIR:-runtime}"
REQUIREMENTS="${REQUIREMENTS_FILE:-requirements-runtime.txt}"
RUNTIME_PLATFORM="${RUNTIME_PLATFORM:?RUNTIME_PLATFORM must be one of macos-arm64, macos-x86_64, windows-arm64, windows-x86_64, linux-arm64, linux-x86_64}"

case "$RUNTIME_PLATFORM" in
  macos-arm64|macos-x86_64|windows-arm64|windows-x86_64|linux-arm64|linux-x86_64) ;;
  *)
    echo "ERROR: unsupported RUNTIME_PLATFORM: $RUNTIME_PLATFORM" >&2
    exit 2
    ;;
esac

# Native-only installation prevents loading foreign extension modules.
host_os="$(uname -s)"
# Git Bash, MSYS2, and Cygwin can report a synthetic uname architecture;
# PowerShell exposes the actual Windows OS architecture.
host_arch=""
if [ "${MSYSTEM:-}" != "" ] || echo "$host_os" | grep -Eq '^(MINGW|MSYS|CYGWIN)'; then
  if command -v powershell.exe >/dev/null 2>&1; then
    raw_arch="$(
      powershell.exe -NoProfile -Command \
        '[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()' \
        2>/dev/null | tr -d '\r' | tail -n 1
    )"
    case "$raw_arch" in
      arm64) host_arch="arm64" ;;
      x64)   host_arch="x86_64" ;;
      x86)   host_arch="x86" ;;
      *)     host_arch="$raw_arch" ;;
    esac
  fi
fi
if [ -z "$host_arch" ]; then
  host_arch="$(uname -m)"
fi
case "$RUNTIME_PLATFORM" in
  macos-arm64)
    [ "$host_os" = "Darwin" ] && [ "$host_arch" = "arm64" ] || {
      echo "ERROR: $RUNTIME_PLATFORM requires native Darwin arm64 (got $host_os/$host_arch)" >&2
      exit 2
    }
    python_bin="$RUNTIME_ROOT/$RUNTIME_PLATFORM/bin/python3"
    ;;
  macos-x86_64)
    [ "$host_os" = "Darwin" ] && [ "$host_arch" = "x86_64" ] || {
      echo "ERROR: $RUNTIME_PLATFORM requires native Darwin x86_64 (got $host_os/$host_arch)" >&2
      exit 2
    }
    python_bin="$RUNTIME_ROOT/$RUNTIME_PLATFORM/bin/python3"
    ;;
  windows-x86_64)
    case "$host_os" in
      MINGW*|MSYS*|CYGWIN*) ;;
      *)
        echo "ERROR: $RUNTIME_PLATFORM requires a native Windows runner (got $host_os/$host_arch)" >&2
        exit 2
        ;;
    esac
    case "$host_arch" in
      x86_64|x64)
        ;;
      *)
        echo "ERROR: $RUNTIME_PLATFORM requires native Windows x86_64 (got $host_os/$host_arch)" >&2
        exit 2
        ;;
    esac
    python_bin="$RUNTIME_ROOT/$RUNTIME_PLATFORM/python.exe"
    ;;
  windows-arm64)
    case "$host_os" in
      MINGW*|MSYS*|CYGWIN*) ;;
      *)
        echo "ERROR: $RUNTIME_PLATFORM requires a native Windows runner (got $host_os/$host_arch)" >&2
        exit 2
        ;;
    esac
    case "$host_arch" in
      arm64)
        ;;
      *)
        echo "ERROR: $RUNTIME_PLATFORM requires native Windows arm64 (got $host_os/$host_arch)" >&2
        exit 2
        ;;
    esac
    python_bin="$RUNTIME_ROOT/$RUNTIME_PLATFORM/python.exe"
    ;;
  linux-x86_64)
    [ "$host_os" = "Linux" ] && [ "$host_arch" = "x86_64" ] || {
      echo "ERROR: $RUNTIME_PLATFORM requires native Linux x86_64 (got $host_os/$host_arch)" >&2
      exit 2
    }
    python_bin="$RUNTIME_ROOT/$RUNTIME_PLATFORM/bin/python3"
    ;;
  linux-arm64)
    case "$host_os" in
      Linux) ;;
      *)
        echo "ERROR: $RUNTIME_PLATFORM requires a native Linux runner (got $host_os/$host_arch)" >&2
        exit 2
        ;;
    esac
    case "$host_arch" in
      aarch64|arm64)
        ;;
      *)
        echo "ERROR: $RUNTIME_PLATFORM requires native Linux arm64 (got $host_os/$host_arch)" >&2
        exit 2
        ;;
    esac
    python_bin="$RUNTIME_ROOT/$RUNTIME_PLATFORM/bin/python3"
    ;;
esac

runtime_dir="$RUNTIME_ROOT/$RUNTIME_PLATFORM"
if [ ! -d "$runtime_dir" ]; then
  echo "ERROR: missing runtime directory: $RUNTIME_PLATFORM" >&2
  exit 1
fi
if [ ! -f "$python_bin" ]; then
  echo "ERROR: missing runtime executable: $RUNTIME_PLATFORM" >&2
  exit 1
fi
if [ ! -f "$REQUIREMENTS" ]; then
  echo "ERROR: missing requirements file: requirements-runtime.txt" >&2
  exit 1
fi

bootstrap_pip() {
  local python_bin="$1"
  if "$python_bin" -c "import pip" 2>/dev/null; then
    return 0
  fi
  echo "  Bootstrapping pip via ensurepip --upgrade..."
  if ! "$python_bin" -m ensurepip --upgrade; then
    echo "ERROR: ensurepip is unavailable and pip is missing for $python_bin" >&2
    echo "ERROR: refusing to fall back to a network-fetched get-pip.py" >&2
    return 1
  fi
  if ! "$python_bin" -c "import pip" 2>/dev/null; then
    echo "ERROR: pip is still not importable after ensurepip for $python_bin" >&2
    return 1
  fi
}

echo "=== Installing deps for $RUNTIME_PLATFORM ==="
bootstrap_pip "$python_bin"
"$python_bin" -m pip install --no-cache-dir --require-hashes -r "$REQUIREMENTS"

# Run the import check with the same interpreter whose native extensions were
# just installed, then write a non-secret readiness receipt beside that runtime.
"$python_bin" "$VERIFY_SCRIPT" check \
  --platform "$RUNTIME_PLATFORM" \
  --runtime-dir "$runtime_dir" \
  --requirements "$REQUIREMENTS"

echo "Dependency installation and readiness verification complete: $RUNTIME_PLATFORM"
