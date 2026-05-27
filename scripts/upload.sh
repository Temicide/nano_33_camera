#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FQBN="${FQBN:-arduino:mbed_nano:nano33ble}"
PORT="${PORT:-}"

if [[ -z "$PORT" ]]; then
  echo "Detecting port (plug in the board via USB)..."
  PORT="$("$ROOT/scripts/port.sh")"
fi

echo "Board: $FQBN"
echo "Port:  $PORT"
arduino-cli compile --fqbn "$FQBN" "$ROOT/nano_33"

UPLOAD_PORT="$PORT"
if [[ "$UPLOAD_PORT" == /dev/cu.* ]]; then
  TTY_PORT="/dev/tty.${UPLOAD_PORT#/dev/cu.}"
  if [[ -e "$TTY_PORT" ]]; then
    UPLOAD_PORT="$TTY_PORT"
  fi
fi

arduino-cli upload -p "$UPLOAD_PORT" --fqbn "$FQBN" "$ROOT/nano_33"
echo "Upload done."
