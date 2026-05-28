#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-}"

ARENA_TARGET_BYTES="${EI_ARENA_TARGET_BYTES:-120000}"
ARENA_MAX_BYTES="${EI_ARENA_MAX_BYTES:-140000}"
EXPECTED_INPUT_WIDTH="${EI_EXPECTED_INPUT_WIDTH:-96}"
EXPECTED_INPUT_HEIGHT="${EI_EXPECTED_INPUT_HEIGHT:-96}"
EXPECTED_FRAME_SIZE="$((EXPECTED_INPUT_WIDTH * EXPECTED_INPUT_HEIGHT))"

if [[ -z "$ZIP" ]]; then
  echo "Usage: $0 <path-to-edge-impulse-arduino-library.zip>"
  echo ""
  echo "Steps:"
  echo "  1. In Edge Impulse Studio -> Deployment -> Arduino Library or C++ Library -> Build"
  echo "  2. Download the .zip file"
  echo "  3. Run: $0 ~/Downloads/your_project_inferencing.zip"
  echo ""
  echo "Memory gate:"
  echo "  target arena <= ${ARENA_TARGET_BYTES} bytes"
  echo "  reject arena > ${ARENA_MAX_BYTES} bytes"
  exit 1
fi

if [[ ! -f "$ZIP" ]]; then
  echo "File not found: $ZIP" >&2
  exit 1
fi

ZIP_LIST="$(mktemp)"
TMP_ROOT="$(mktemp -d)"
trap 'rm -f "$ZIP_LIST"; rm -rf "$TMP_ROOT"' EXIT
unzip -Z1 "$ZIP" > "$ZIP_LIST"

LIBS_DIR="${ARDUINO_LIBS:-$HOME/Documents/Arduino/libraries}"
LIB_NAME="pill_counting_inferencing"
LIB_DIR="$LIBS_DIR/$LIB_NAME"
STAGED_LIB="$TMP_ROOT/$LIB_NAME"
mkdir -p "$LIBS_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

macro_value() {
  local file="$1"
  local name="$2"
  awk -v name="$name" '$1 == "#define" && $2 == name { print $3; exit }' "$file" | tr -d '\r'
}

max_compiled_arena() {
  local dir="$1"
  find "$dir/src/tflite-model" -type f -name '*compiled.cpp' 2>/dev/null |
    xargs awk '
      /kTensorArenaSize =/ {
        line = $0
        gsub(/[^0-9]/, "", line)
        if (line > max) {
          max = line
        }
      }
      END {
        if (max != "") {
          print max
        }
      }
    '
}

normalize_library_properties() {
  local props="$1"
  [[ -f "$props" ]] || return 0

  perl -0pi -e '
    s/^name=.*/name=pill_counting_inferencing/m;
    if (/^architectures=/m) {
      s/^architectures=.*/architectures=mbed_nano/m;
    }
    else {
      $_ .= "\narchitectures=mbed_nano\n";
    }
    if (/^includes=/m) {
      s/^includes=.*/includes=pill_counting_inferencing.h/m;
    }
    else {
      $_ .= "includes=pill_counting_inferencing.h\n";
    }
  ' "$props"
}

ensure_wrapper_header() {
  local dir="$1"
  local wrapper="$dir/src/pill_counting_inferencing.h"

  if [[ -f "$wrapper" ]]; then
    return 0
  fi

  local inferencing_header
  inferencing_header="$(find "$dir/src" -maxdepth 1 -type f -name '*_inferencing.h' -print | head -n 1)"
  if [[ -n "$inferencing_header" ]]; then
    local header_basename
    header_basename="$(basename "$inferencing_header")"
    cat > "$wrapper" <<EOF_HEADER
#ifndef PILL_COUNTING_INFERENCING_H_
#define PILL_COUNTING_INFERENCING_H_

#include "$header_basename"

#endif // PILL_COUNTING_INFERENCING_H_
EOF_HEADER
    return 0
  fi

  if [[ -f "$dir/src/model-parameters/model_metadata.h" &&
        -f "$dir/src/edge-impulse-sdk/classifier/ei_run_classifier.h" ]]; then
    cat > "$wrapper" <<'EOF_HEADER'
#ifndef PILL_COUNTING_INFERENCING_H_
#define PILL_COUNTING_INFERENCING_H_

#include "model-parameters/model_metadata.h"
#include "edge-impulse-sdk/classifier/ei_run_classifier.h"

#endif // PILL_COUNTING_INFERENCING_H_
EOF_HEADER
    return 0
  fi

  fail "could not create pill_counting_inferencing.h wrapper"
}

patch_export_for_nano33() {
  local dir="$1"

  if [[ -f "$dir/src/edge-impulse-sdk/porting/ei_classifier_porting.h" ]]; then
    perl -0pi -e 's/#ifndef EI_PORTING_MBED\n#ifdef __MBED__\n#define EI_PORTING_MBED      1\n#else\n#define EI_PORTING_MBED      0\n#endif\n#endif/#ifndef EI_PORTING_MBED\n#define EI_PORTING_MBED      0\n#endif/s' \
      "$dir/src/edge-impulse-sdk/porting/ei_classifier_porting.h"
  fi

  local metadata="$dir/src/model-parameters/model_metadata.h"
  local variables="$dir/src/model-parameters/model_variables.h"
  if [[ -f "$metadata" && -f "$variables" ]]; then
    perl -0pi -e 's/(#define EI_CLASSIFIER_OBJECT_DETECTION_THRESHOLD\s+)0\.5/${1}0.0/g; s/(\.threshold\s*=\s*)0\.5/${1}0.0/g' \
      "$metadata" \
      "$variables"
  fi
}

install_cpp_export() {
  local dir="$1"
  echo "Staging Edge Impulse C++ export: $dir"
  mkdir -p "$dir/src"

  unzip -q "$ZIP" 'edge-impulse-sdk/*' 'model-parameters/*' 'tflite-model/*' -d "$dir/src"
  unzip -q "$ZIP" 'README.txt' -d "$dir/src" 2>/dev/null || true
  if [[ -f "$dir/src/README.txt" ]]; then
    mv "$dir/src/README.txt" "$dir/README.txt"
  fi

  cat > "$dir/library.properties" <<EOF_LIBRARY
name=$LIB_NAME
version=1.0.0
author=Edge Impulse
maintainer=Temicide
sentence=Edge Impulse inferencing library for pill-counting.
paragraph=Arduino-compatible wrapper around the Edge Impulse C++ MCU deployment for pill-counting.
category=Data Processing
url=https://studio.edgeimpulse.com/studio/1011420
architectures=mbed_nano
includes=pill_counting_inferencing.h
EOF_LIBRARY

  ensure_wrapper_header "$dir"
  patch_export_for_nano33 "$dir"
}

install_arduino_export() {
  local dir="$1"
  local extract_dir="$TMP_ROOT/arduino_export"
  mkdir -p "$extract_dir" "$dir"

  echo "Staging Edge Impulse Arduino library export: $dir"
  unzip -q "$ZIP" -d "$extract_dir"

  local props
  props="$(find "$extract_dir" -type f -name library.properties -print | head -n 1)"
  [[ -n "$props" ]] || fail "Arduino library ZIP does not contain library.properties"

  local source_dir
  source_dir="$(dirname "$props")"
  cp -R "$source_dir"/. "$dir"/

  normalize_library_properties "$dir/library.properties"
  ensure_wrapper_header "$dir"
  patch_export_for_nano33 "$dir"
}

validate_model() {
  local dir="$1"
  local metadata="$dir/src/model-parameters/model_metadata.h"
  [[ -f "$metadata" ]] || fail "model metadata not found at $metadata"

  local width height raw_count samples_per_frame nn_frame input_type engine deploy largest_arena compiled_arena effective_arena
  width="$(macro_value "$metadata" EI_CLASSIFIER_INPUT_WIDTH)"
  height="$(macro_value "$metadata" EI_CLASSIFIER_INPUT_HEIGHT)"
  raw_count="$(macro_value "$metadata" EI_CLASSIFIER_RAW_SAMPLE_COUNT)"
  samples_per_frame="$(macro_value "$metadata" EI_CLASSIFIER_RAW_SAMPLES_PER_FRAME)"
  nn_frame="$(macro_value "$metadata" EI_CLASSIFIER_NN_INPUT_FRAME_SIZE)"
  input_type="$(macro_value "$metadata" EI_CLASSIFIER_TFLITE_INPUT_DATATYPE)"
  engine="$(macro_value "$metadata" EI_CLASSIFIER_INFERENCING_ENGINE)"
  deploy="$(macro_value "$metadata" EI_CLASSIFIER_PROJECT_DEPLOY_VERSION)"
  largest_arena="$(macro_value "$metadata" EI_CLASSIFIER_TFLITE_LARGEST_ARENA_SIZE)"
  compiled_arena="$(max_compiled_arena "$dir" || true)"
  effective_arena="$largest_arena"
  if [[ -z "$effective_arena" || ! "$effective_arena" =~ ^[0-9]+$ ]]; then
    effective_arena="$compiled_arena"
  fi

  echo ""
  echo "Edge Impulse metadata:"
  echo "  deploy_version: ${deploy:-unknown}"
  echo "  input:          ${width:-?}x${height:-?}"
  echo "  raw_frame:      ${raw_count:-?} samples x ${samples_per_frame:-?}"
  echo "  nn_frame:       ${nn_frame:-?}"
  echo "  input_type:     ${input_type:-unknown}"
  echo "  engine:         ${engine:-unknown}"
  echo "  largest_arena:  ${largest_arena:-unknown}"
  echo "  compiled_arena: ${compiled_arena:-unknown}"

  [[ "$width" == "$EXPECTED_INPUT_WIDTH" ]] ||
    fail "expected EI input width ${EXPECTED_INPUT_WIDTH}, got ${width:-unknown}"
  [[ "$height" == "$EXPECTED_INPUT_HEIGHT" ]] ||
    fail "expected EI input height ${EXPECTED_INPUT_HEIGHT}, got ${height:-unknown}"
  [[ "$samples_per_frame" == "1" ]] ||
    fail "expected grayscale/raw samples per frame 1, got ${samples_per_frame:-unknown}"
  [[ "$raw_count" == "$EXPECTED_FRAME_SIZE" || "$nn_frame" == "$EXPECTED_FRAME_SIZE" ]] ||
    fail "expected ${EXPECTED_FRAME_SIZE} grayscale input samples, got raw=${raw_count:-unknown} nn=${nn_frame:-unknown}"
  [[ "$input_type" == "EI_CLASSIFIER_DATATYPE_INT8" || "$input_type" == "9" ]] ||
    fail "expected int8 quantized model input, got ${input_type:-unknown}"
  [[ -n "$effective_arena" && "$effective_arena" =~ ^[0-9]+$ ]] ||
    fail "could not determine Edge Impulse arena size"

  if (( effective_arena > ARENA_MAX_BYTES )); then
    fail "arena ${effective_arena} exceeds hard limit ${ARENA_MAX_BYTES}; re-export with MobileNetV2 0.1 or EON RAM Optimized"
  fi
  if (( effective_arena > ARENA_TARGET_BYTES )); then
    echo "WARNING: arena ${effective_arena} exceeds target ${ARENA_TARGET_BYTES}; deploy is allowed but headroom is tight." >&2
  fi
}

if grep -Eq '(^|/)library\.properties$' "$ZIP_LIST"; then
  install_arduino_export "$STAGED_LIB"
elif grep -qx 'edge-impulse-sdk/classifier/ei_run_classifier.h' "$ZIP_LIST" &&
     grep -qx 'model-parameters/model_metadata.h' "$ZIP_LIST" &&
     grep -Eq '^tflite-model/.*compiled\.cpp$' "$ZIP_LIST"; then
  install_cpp_export "$STAGED_LIB"
else
  fail "ZIP is not an Edge Impulse Arduino Library or C++ MCU export: $ZIP"
fi

validate_model "$STAGED_LIB"

rm -rf "$LIB_DIR"
mv "$STAGED_LIB" "$LIB_DIR"

echo ""
echo "Library installed: $LIB_DIR"
echo "Now compile and upload:"
echo "  ./scripts/upload.sh"
