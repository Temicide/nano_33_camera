#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FQBN="${FQBN:-arduino:mbed_nano:nano33ble}"
PORT="${PORT:-}"
SKIP_UPLOAD="${SKIP_UPLOAD:-0}"
RAM_WARN_BYTES="${RAM_WARN_BYTES:-210000}"
RAM_MAX_BYTES="${RAM_MAX_BYTES:-220000}"
EI_EXTRA_FLAGS="${EI_EXTRA_FLAGS:--DEI_CLASSIFIER_ALLOCATION_STATIC}"

COMPILE_LOG="$(mktemp)"
trap 'rm -f "$COMPILE_LOG"' EXIT

echo "Board: $FQBN"
echo "Flags: $EI_EXTRA_FLAGS"
arduino-cli compile \
  --fqbn "$FQBN" \
  --build-property "compiler.c.extra_flags=$EI_EXTRA_FLAGS" \
  --build-property "compiler.cpp.extra_flags=$EI_EXTRA_FLAGS" \
  "$ROOT/nano_33" 2>&1 | tee "$COMPILE_LOG"

DYNAMIC_BYTES="$(
  awk '/Global variables use/ {
    gsub(/,/, "", $4);
    print $4;
  }' "$COMPILE_LOG" | tail -n 1
)"

if [[ -z "$DYNAMIC_BYTES" ]]; then
  echo "ERROR: could not parse Arduino dynamic memory usage from compile output." >&2
  exit 1
fi

echo "Dynamic memory: ${DYNAMIC_BYTES} bytes"
if (( DYNAMIC_BYTES > RAM_MAX_BYTES )); then
  echo "ERROR: dynamic memory ${DYNAMIC_BYTES} exceeds hard limit ${RAM_MAX_BYTES}." >&2
  echo "Re-export the Edge Impulse model with a smaller arena before uploading." >&2
  exit 1
fi
if (( DYNAMIC_BYTES > RAM_WARN_BYTES )); then
  echo "WARNING: dynamic memory ${DYNAMIC_BYTES} exceeds target ${RAM_WARN_BYTES}." >&2
fi

if [[ "$SKIP_UPLOAD" == "1" ]]; then
  echo "Compile-only mode; skipping upload."
  exit 0
fi

if [[ -z "$PORT" ]]; then
  echo "Detecting port (plug in the board via USB)..."
  PORT="$("$ROOT/scripts/port.sh")"
fi

echo "Port:  $PORT"

UPLOAD_PORT="$PORT"
if [[ "$UPLOAD_PORT" == /dev/cu.* ]]; then
  TTY_PORT="/dev/tty.${UPLOAD_PORT#/dev/cu.}"
  if [[ -e "$TTY_PORT" ]]; then
    UPLOAD_PORT="$TTY_PORT"
  fi
fi

arduino-cli upload -p "$UPLOAD_PORT" --fqbn "$FQBN" "$ROOT/nano_33"
echo "Upload done."
