#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$ROOT/scripts"

PORT="${PORT:-$("$SCRIPT_DIR/port.sh")}"

echo "Starting board-side detection collector on $PORT..."
exec "$ROOT/.venv/bin/python" "$SCRIPT_DIR/detect_data_collector.py" --port "$PORT" "$@"
