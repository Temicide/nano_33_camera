#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$ROOT/scripts"

PORT="${PORT:-$("$SCRIPT_DIR/port.sh")}"

echo "Starting live detection view on $PORT..."
exec "$ROOT/.venv/bin/python" "$SCRIPT_DIR/live_detect_view.py" --port "$PORT" "$@"
