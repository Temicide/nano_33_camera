#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$ROOT/scripts"

PORT="${PORT:-$("$SCRIPT_DIR/port.sh")}"

echo "Starting live camera view on $PORT..."
exec "$ROOT/.venv/bin/python" "$SCRIPT_DIR/live_camera_view.py" --port "$PORT" "$@"
