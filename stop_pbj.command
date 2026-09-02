#!/bin/zsh

set -u

PBJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
PBJ_PORTS=(8000 8001)
stopped=0
typeset -a pbj_terminal_ttys

close_launcher_terminal() {
  if [[ "${TERM_PROGRAM:-}" != "Apple_Terminal" ]]; then
    return
  fi

  # Close the Terminal window that launched PBJ and the separate window that
  # launched this stop command. The process TTYs keep unrelated windows safe.
  (
    sleep 0.5
    osascript \
      -e 'on run targetTTYs' \
      -e 'tell application "Terminal"' \
      -e 'set stopWindow to front window' \
      -e 'repeat with targetTTY in targetTTYs' \
      -e 'repeat with terminalWindow in windows' \
      -e 'try' \
      -e 'if tty of selected tab of terminalWindow is targetTTY then close terminalWindow' \
      -e 'end try' \
      -e 'end repeat' \
      -e 'end repeat' \
      -e 'try' \
      -e 'close stopWindow' \
      -e 'end try' \
      -e 'end tell' \
      -e 'end run' \
      "${pbj_terminal_ttys[@]}" >/dev/null 2>&1
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

    if [[ "$process_root" == "$PBJ_ROOT" && "$process_command" == *"uvicorn"*"app.main:app"* ]]; then
      process_tty="$(ps -p "$pid" -o tty= 2>/dev/null | tr -d '[:space:]')"
      if [[ -n "$process_tty" && "$process_tty" != "??" ]]; then
        [[ "$process_tty" == /dev/* ]] || process_tty="/dev/$process_tty"
        if (( ${pbj_terminal_ttys[(Ie)$process_tty]} == 0 )); then
          pbj_terminal_ttys+=("$process_tty")
        fi
      fi
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
