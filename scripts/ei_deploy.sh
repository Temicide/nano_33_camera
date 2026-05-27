#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-}"

if [[ -z "$ZIP" ]]; then
  echo "Usage: $0 <path-to-edge-impulse-arduino-library.zip>"
  echo ""
  echo "Steps:"
  echo "  1. In Edge Impulse Studio → Deployment → Arduino Library → Build"
  echo "  2. Download the .zip file"
  echo "  3. Run: $0 ~/Downloads/your_project_inferencing.zip"
  exit 1
fi

if [[ ! -f "$ZIP" ]]; then
  echo "File not found: $ZIP"
  exit 1
fi

LIBS_DIR="${ARDUINO_LIBS:-$HOME/Documents/Arduino/libraries}"
mkdir -p "$LIBS_DIR"

echo "Extracting $ZIP → $LIBS_DIR"
unzip -o "$ZIP" -d "$LIBS_DIR"

echo ""
echo "Library installed. Now compile and upload:"
echo "  ./scripts/upload.sh"
