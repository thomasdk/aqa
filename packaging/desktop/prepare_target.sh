#!/usr/bin/env bash
# Stage one native-runtime AQA payload for Tauri. This intentionally has a
# narrow allowlist: no settings, conversations, credentials, cache, or other
# mutable data can cross the staging boundary.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

TARGET="${1:?usage: prepare_target.sh <macos-arm64|macos-x86_64|windows-arm64|windows-x86_64|linux-arm64|linux-x86_64>}"
case "$TARGET" in
  macos-arm64|macos-x86_64|windows-arm64|windows-x86_64|linux-arm64|linux-x86_64) ;;
  *) echo "Unsupported desktop target: $TARGET" >&2; exit 2 ;;
esac

STAGE_ROOT="${AQA_DESKTOP_STAGE_ROOT:-$PROJECT_ROOT/desktop/src-tauri/resources/backend}"
PYTHON_FOR_TOOLS="${PYTHON_FOR_TOOLS:-python3}"

"$PYTHON_FOR_TOOLS" packaging/runtime/verify_runtime.py validate-one \
  --runtime-root runtime --requirements requirements-runtime.txt \
  --platform "$TARGET" --allow-cross-staged

"$PYTHON_FOR_TOOLS" packaging/licensing/generate_rust_notices.py --check
(cd frontend && npm run build)

rm -rf "$STAGE_ROOT"
mkdir -p "$STAGE_ROOT/src" "$STAGE_ROOT/data" "$STAGE_ROOT/frontend" "$STAGE_ROOT/licenses"

install -m 0644 LICENSE "$STAGE_ROOT/licenses/AQA-LICENSE.txt"
install -m 0644 THIRD_PARTY_NOTICES.md "$STAGE_ROOT/licenses/THIRD_PARTY_NOTICES.md"
rsync -a --safe-links THIRD_PARTY_LICENSES/ "$STAGE_ROOT/licenses/third-party/"

for file in src/__init__.py src/api_server.py src/desktop_server.py src/server_logging.py; do
  install -m 0644 "$file" "$STAGE_ROOT/$file"
done
for package in config llm local_ai prompts service; do
  while IFS= read -r -d '' file; do
    relative="${file#src/}"
    install -d "$STAGE_ROOT/src/$(dirname "$relative")"
    install -m 0644 "$file" "$STAGE_ROOT/src/$relative"
  done < <(find "src/$package" -type f -name '*.py' -print0)
done

for data_dir in prompts prompt_defaults tokenizers; do
  [ -d "data/$data_dir" ] && rsync -a --safe-links "data/$data_dir" "$STAGE_ROOT/data/"
done
rsync -a --safe-links frontend/dist "$STAGE_ROOT/frontend/"
rsync -a --safe-links "runtime/$TARGET/" "$STAGE_ROOT/runtime/"

# Tauri requires frontendDist even though the real window is opened only after
# the FastAPI health gate. This inert page is never exposed to product users.
LOADING_DIR="$PROJECT_ROOT/desktop/src-tauri/resources/loading"
mkdir -p "$LOADING_DIR"
printf '%s\n' '<!doctype html><title>AQA</title><p>Starting AQA…</p>' > "$LOADING_DIR/index.html"

# File names alone are sufficient for this safety audit; never print contents.
if find "$STAGE_ROOT" \( -name '.env' -o -name 'settings.json' -o -name '*.log' -o -name '*.db' -o -name '*.sqlite' \) -print -quit | grep -q .; then
  echo "Refusing unsafe desktop stage: prohibited mutable or secret-looking file found" >&2
  exit 1
fi
if [ ! -f "$STAGE_ROOT/runtime/.aqa-runtime-ready.json" ]; then
  echo "Refusing desktop stage: selected runtime has no readiness receipt" >&2
  exit 1
fi
"$PYTHON_FOR_TOOLS" packaging/runtime/verify_runtime.py audit-unsafe-symlinks \
  --runtime-root "$STAGE_ROOT/runtime" --strip
"$PYTHON_FOR_TOOLS" packaging/licensing/verify_staged_licenses.py "$STAGE_ROOT"
find "$STAGE_ROOT" -type f -print | sed "s#^$STAGE_ROOT/##" | sort > "$STAGE_ROOT/.aqa-desktop-stage-manifest.txt"
echo "Prepared Tauri backend payload for $TARGET at $STAGE_ROOT"
