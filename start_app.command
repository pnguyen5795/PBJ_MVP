#!/bin/zsh
set -euo pipefail

PBJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
PBJ_PORT=8000

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

cleanup() {
  [ -n "${PBJ_PID:-}" ] && kill -TERM "$PBJ_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting PBJ..."
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PBJ_PORT" &
PBJ_PID=$!

for _ in {1..120}; do
  if curl -fsS "http://127.0.0.1:$PBJ_PORT/manifest.webmanifest" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$PBJ_PID" 2>/dev/null; then
    echo "PBJ stopped during startup. Review the messages above."
    exit 1
  fi
  sleep 0.25
done

if ! curl -fsS "http://127.0.0.1:$PBJ_PORT/manifest.webmanifest" >/dev/null 2>&1; then
  echo "PBJ did not become ready in time."
  exit 1
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
echo "PBJ is ready at http://127.0.0.1:$PBJ_PORT"
if [ -n "$LAN_IP" ]; then
  echo "On an iPhone using the same trusted Wi-Fi, open http://$LAN_IP:$PBJ_PORT"
fi
echo "Keep this window open. Press Control-C to stop PBJ."
open "http://127.0.0.1:$PBJ_PORT"

wait "$PBJ_PID"
