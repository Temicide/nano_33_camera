#!/usr/bin/env bash
# Print the serial port for Arduino Nano 33 BLE (or first USB modem as fallback).
set -euo pipefail

port="$(
  arduino-cli board list 2>/dev/null | awk '
    /Arduino Nano 33/ && /usbmodem|usbserial/ { print $1; exit }
    /nano33ble/ && /usbmodem|usbserial/ { print $1; exit }
    /usbmodem|usbserial/ && !fallback { fallback = $1 }
    END { if (fallback) print fallback }
  '
)"

if [[ -z "$port" ]]; then
  echo "No Nano 33 USB port found. Plug in the board and run: arduino-cli board list" >&2
  exit 1
fi

if [[ ! -e "$port" ]]; then
  echo "Port missing: $port — run: arduino-cli board list" >&2
  exit 1
fi

echo "$port"
