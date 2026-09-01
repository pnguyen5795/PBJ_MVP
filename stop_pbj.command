#!/bin/zsh

set -u

PBJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
PBJ_PORTS=(8000 8001 5173)
stopped=0
launcher_tty="$(tty 2>/dev/null || true)"

close_launcher_terminal() {
  if [[ "${TERM_PROGRAM:-}" != "Apple_Terminal" || "$launcher_tty" != /dev/* ]]; then
    return
  fi

  # Let this script finish, then close only the Terminal tab that launched it.
  (
    sleep 0.3
    osascript \
      -e 'on run argv' \
      -e 'set targetTTY to item 1 of argv' \
      -e 'tell application "Terminal"' \
      -e 'repeat with terminalWindow in windows' \
      -e 'repeat with terminalTab in tabs of terminalWindow' \
      -e 'if tty of terminalTab is targetTTY then' \
      -e 'close terminalTab' \
      -e 'return' \
      -e 'end if' \
      -e 'end repeat' \
      -e 'end repeat' \
      -e 'end tell' \
      -e 'end run' \
      "$launcher_tty" >/dev/null 2>&1
  ) &!
}

trap close_launcher_terminal EXIT

stop_process_tree() {
  local parent_pid="$1"
  local child_pid

  for child_pid in $(pgrep -P "$parent_pid" 2>/dev/null); do
    stop_process_tree "$child_pid"
  done
  kill -TERM "$parent_pid" 2>/dev/null || true
}

for port in "${PBJ_PORTS[@]}"; do
  for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
    process_root=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
    process_command=$(ps -p "$pid" -o command= 2>/dev/null)

    if [[ ( "$process_root" == "$PBJ_ROOT" && "$process_command" == *"uvicorn"*"app.main:app"* ) ||
          ( "$port" == "5173" && "$process_root" == "$PBJ_ROOT/.evaluations/openreel-video"* ) ]]; then
      stop_process_tree "$pid"
      stopped=$((stopped + 1))
    fi
  done
done

if (( stopped == 0 )); then
  print "PBJ was already stopped."
else
  # Give PBJ a moment to finish its normal shutdown before reporting success.
  for _ in {1..30}; do
    still_running=0
    for port in "${PBJ_PORTS[@]}"; do
      if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        still_running=1
      fi
    done
    (( still_running == 0 )) && break
    sleep 0.1
  done
  print "PBJ is stopped. You can start it again now."
fi
