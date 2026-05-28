#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PORT="${PORT:-$("$SCRIPT_DIR/port.sh")}"

echo "Monitoring $PORT at 921600 baud (Ctrl-C to exit)"
exec arduino-cli monitor -p "$PORT" -c baudrate=921600
