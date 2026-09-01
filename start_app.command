#!/bin/zsh
set -euo pipefail

PBJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
OPENREEL_ROOT="$PBJ_ROOT/.evaluations/openreel-video"
PBJ_PORT=8000
OPENREEL_PORT=5173

cd "$PBJ_ROOT"

if [ ! -x ".venv/bin/python" ]; then
  echo "Preparing PBJ for first use..."
  PYTHON_BIN="$(command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || true)"
  if [ -z "$PYTHON_BIN" ]; then
    echo "PBJ needs Python 3.12 or newer. Install it, then run this launcher again."
    exit 1
  fi
  "$PYTHON_BIN" -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

if [ ! -d "$OPENREEL_ROOT/apps/web" ]; then
  echo "OpenReel is not available at $OPENREEL_ROOT"
  echo "Run scripts/setup_openreel.command once, then start the combined app again."
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
  echo "OpenReel needs Node.js 24 and pnpm 11. Install them, then run this launcher again."
  exit 1
fi

if [ ! -d "$OPENREEL_ROOT/node_modules" ]; then
  echo "OpenReel dependencies are not installed. Run scripts/setup_openreel.command"
  echo "after moving the incomplete checkout aside."
  exit 1
fi

cleanup() {
  [ -n "${OPENREEL_PID:-}" ] && kill -TERM "$OPENREEL_PID" 2>/dev/null || true
  [ -n "${PBJ_PID:-}" ] && kill -TERM "$PBJ_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting PBJ and OpenReel..."
PATH="$(dirname "$NODE_BIN"):$(dirname "$PNPM_BIN"):$PATH" \
  "$PNPM_BIN" --dir "$OPENREEL_ROOT" --filter @openreel/web dev --host 0.0.0.0 --port "$OPENREEL_PORT" &
OPENREEL_PID=$!

PBJ_OPENREEL_PORT="$OPENREEL_PORT" .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PBJ_PORT" &
PBJ_PID=$!

for _ in {1..120}; do
  if curl -fsS "http://127.0.0.1:$PBJ_PORT/manifest.webmanifest" >/dev/null 2>&1 && \
     curl -fsS "http://127.0.0.1:$OPENREEL_PORT" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$PBJ_PID" 2>/dev/null || ! kill -0 "$OPENREEL_PID" 2>/dev/null; then
    echo "PBJ or OpenReel stopped during startup. Review the messages above."
    exit 1
  fi
  sleep 0.25
done

if ! curl -fsS "http://127.0.0.1:$PBJ_PORT/manifest.webmanifest" >/dev/null 2>&1 || \
   ! curl -fsS "http://127.0.0.1:$OPENREEL_PORT" >/dev/null 2>&1; then
  echo "PBJ and OpenReel did not become ready in time."
  exit 1
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
echo "PBJ and OpenReel are ready at http://127.0.0.1:$PBJ_PORT"
if [ -n "$LAN_IP" ]; then
  echo "On an iPhone using the same trusted Wi-Fi, open http://$LAN_IP:$PBJ_PORT"
fi
echo "Keep this window open. Press Control-C to stop both services."
open "http://127.0.0.1:$PBJ_PORT"

wait "$PBJ_PID" "$OPENREEL_PID"
