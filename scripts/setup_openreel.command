#!/bin/zsh
set -euo pipefail

PBJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OPENREEL_ROOT="$PBJ_ROOT/.evaluations/openreel-video"
OPENREEL_REVISION="5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9"
OPENREEL_REPOSITORY="https://github.com/Augani/openreel-video.git"
PBJ_PATCH="$PBJ_ROOT/integrations/openreel/openreel-pbj.patch"

if ! command -v git >/dev/null 2>&1; then
  echo "Git is required to download the reviewed OpenReel source."
  exit 1
fi

if [ -e "$OPENREEL_ROOT" ]; then
  echo "OpenReel already exists at:"
  echo "$OPENREEL_ROOT"
  echo "Move that checkout aside before running setup again."
  exit 1
fi

if [ ! -f "$PBJ_PATCH" ]; then
  echo "PBJ's OpenReel patch is missing: $PBJ_PATCH"
  exit 1
fi

NODE_BIN="$(command -v node 2>/dev/null || true)"
PNPM_BIN="$(command -v pnpm 2>/dev/null || true)"
if [ -z "$NODE_BIN" ] || [ -z "$PNPM_BIN" ]; then
  USER_DIR="/Users/$(id -un)"
  BUNDLED_ROOT="$USER_DIR/.cache/codex-runtimes/codex-primary-runtime/dependencies"
  [ -x "$BUNDLED_ROOT/node/bin/node" ] && NODE_BIN="$BUNDLED_ROOT/node/bin/node"
  [ -x "$BUNDLED_ROOT/bin/fallback/pnpm" ] && PNPM_BIN="$BUNDLED_ROOT/bin/fallback/pnpm"
fi
if [ -z "$NODE_BIN" ] || [ -z "$PNPM_BIN" ]; then
  echo "Install Node.js 24 and pnpm 11 before setting up OpenReel."
  exit 1
fi

mkdir -p "$PBJ_ROOT/.evaluations"
echo "Cloning the reviewed OpenReel source..."
git clone --no-checkout "$OPENREEL_REPOSITORY" "$OPENREEL_ROOT"
git -C "$OPENREEL_ROOT" checkout --detach "$OPENREEL_REVISION"

echo "Applying the PBJ integration patch..."
git -C "$OPENREEL_ROOT" apply --check "$PBJ_PATCH"
git -C "$OPENREEL_ROOT" apply "$PBJ_PATCH"

echo "Installing OpenReel dependencies..."
PATH="$(dirname "$NODE_BIN"):$(dirname "$PNPM_BIN"):$PATH" \
  "$PNPM_BIN" --dir "$OPENREEL_ROOT" install --frozen-lockfile

echo "Checking the OpenReel web application..."
PATH="$(dirname "$NODE_BIN"):$(dirname "$PNPM_BIN"):$PATH" \
  "$PNPM_BIN" --dir "$OPENREEL_ROOT" --filter @openreel/web typecheck

echo "OpenReel is ready. Start PBJ with start_app.command."
