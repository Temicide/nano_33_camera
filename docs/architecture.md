# Architecture Overview

Last updated: 2026-05-28

This project runs a complete medicine blister-cell counting loop on an Arduino
Nano 33 BLE. The board captures grayscale camera frames, runs an Edge Impulse
FOMO detector on-device, then streams either frame bytes or count results over
USB serial to host-side Python tools.

## System Design

```text
TinyML Shield OV7675 camera
        |
        v
nano_33/nano_33.ino
  - capture 160x120 grayscale frames
  - crop/resize into Edge Impulse's 96x96 input through signal callback
  - run FOMO inference on the board
  - emit serial text, JSON, OVF1 frames, or OVD1 detection packets
        |
        v
USB serial at 921600 baud
        |
        +--> scripts/live_camera_view.py      OpenCV raw-frame viewer
        +--> scripts/live_detect_view.py      OpenCV detection viewer
        +--> scripts/detect_web.py            Flask MJPEG detection UI
        +--> scripts/data_collector.py        Browser capture workflow
        +--> scripts/detect_data_collector.py Detection-assisted capture workflow
        +--> scripts/test_training_data.py    Offline model sanity check
```

The firmware is the source of truth for camera geometry, model preprocessing,
serial command behavior, and detection filtering. Host tools should parse the
firmware protocols instead of duplicating inference decisions.

## Directory Structure

```text
nano_33/
|-- nano_33/nano_33.ino       # Firmware: capture, inference, exposure, serial protocol
|-- scripts/                  # Shell entrypoints and Python host tools
|   |-- upload.sh             # Compile/upload wrapper with RAM guardrails
|   |-- port.sh               # Nano 33 serial-port discovery
|   |-- *_view.py             # OpenCV serial viewers
|   |-- detect_web.py         # Flask detection dashboard
|   |-- *_collector.py        # Training image capture workflows
|   `-- test_training_data.py # Offline Edge Impulse runner for captured images
|-- scripts/templates/        # Flask templates for browser tools
|-- docs/training_data/       # Captured blister_0001.png images and JSON metadata
|-- docs/research/            # Experiments, reports, and research notes
|-- docs/model_and_ram.md     # Model/RAM background and deployment rationale
|-- data/                     # Analysis CSVs
`-- nano33-course/            # Generated learning material for new contributors
```

Generated local outputs such as `build/`, `captures/`, `logs/`, `.venv/`, and
`compile_flags.txt` are not part of the architecture contract.

## Firmware Responsibilities

The sketch in `nano_33/nano_33.ino` owns the board runtime:

- Initializes the TinyML Shield OV7675 camera in QQVGA grayscale mode.
- Maintains one 160x120 frame buffer to keep RAM usage inside the Nano 33 BLE
  budget.
- Builds lookup tables that map the 96x96 model input back into the 160x120
  camera frame using Edge Impulse's `EI_CLASSIFIER_RESIZE_FIT_SHORTEST`
  behavior.
- Implements `ei_get_frame_data()` so Edge Impulse can pull model features from
  the camera buffer without allocating a second resized image.
- Filters inference output to `blister` detections with confidence at least
  `0.5`.
- Maps model-space boxes back to camera-frame coordinates for host display.
- Exposes serial commands for streaming, counting, profiling, memory checks,
  and exposure modes.

The firmware intentionally keeps preprocessing on the board. That makes raw
serial captures, detection packets, JSON counts, and offline checks easier to
compare because they all use the same crop/resize assumptions.

## Runtime Data Flow

### Raw Frame Streaming

1. Host sends `S`.
2. Firmware captures one grayscale frame into `g_frame`.
3. Firmware writes an `OVF1` binary header.
4. Firmware writes `160 * 120` grayscale bytes.
5. Host tools scan for `OVF1`, unpack the header, decode the frame, and display
   or save it.

Use this mode for live camera inspection, exposure tuning, and data capture when
model output is not needed.

### Detection Streaming

1. Host sends `D`.
2. Firmware captures a grayscale frame.
3. Firmware runs `run_classifier()` through the Edge Impulse signal callback.
4. Firmware filters target boxes and writes an `OVD1` binary header.
5. Firmware writes fixed-width detection records, then the frame bytes.
6. Host tools draw boxes and report FPS/counts.

This is the main mode for `scripts/detect_web.py` and the detection viewers.

### Production Count

1. Host sends `J`.
2. Firmware captures one frame and runs inference once.
3. Firmware prints one JSON line with `ok`, `count`, `boxes`, and `timing_ms`.

Use this mode for production-style checks because it returns a compact result
without requiring the host to parse image packets.

## Serial Protocol

The firmware announces readiness with `NANO33_OV7675_READY` at `921600` baud.

Binary frame packets are little-endian:

```text
OVF1 raw frame packet
magic[4]          "OVF1"
width             uint16
height            uint16
bytes_per_pixel   uint8
format            uint8, 0 = grayscale
frame_number      uint32
frame_size        uint32
frame_data        uint8[frame_size]

OVD1 detection packet
magic[4]          "OVD1"
width             uint16
height            uint16
bytes_per_pixel   uint8
format            uint8, 0 = grayscale
frame_number      uint32
frame_size        uint32
detection_count   uint16
detections        repeated uint16 x, y, w, h, confidence_0_to_10000
frame_data        uint8[frame_size]
```

Text commands:

| Command | Purpose | Typical consumer |
| --- | --- | --- |
| `S` | Start raw frame streaming | `live_camera_view.py`, collectors |
| `P` | Pause streaming | Viewers and collectors on exit |
| `D` | Start detection packet streaming | `detect_web.py`, detection viewers |
| `X` | Stop count/detection mode | Browser controls |
| `J` | Single JSON count | Production checks |
| `C` | Single text count with verbose detections | Manual debugging |
| `K` | Continuous text count mode | Bench/debug sessions |
| `T` | Timing profile | Performance checks |
| `M` | Memory/model diagnostics | RAM validation |
| `F` | Manual face/exposure preset | Lighting tests |
| `A` | Auto exposure | Default viewing |
| `c` | Calibrated fixed exposure preset | Repeatable data capture |
| `?` | Print status/help | Manual debugging |

## Host Tool Boundaries

Shell scripts in `scripts/*.sh` are entrypoints. They set paths, locate the
board, and invoke Arduino CLI or Python tools.

Python tools handle host-side concerns only:

- Port detection and serial reconnect behavior.
- Packet synchronization by scanning for binary magic values.
- OpenCV or browser rendering.
- Capture file naming and metadata writes.
- Offline testing against stored training images.

The browser tools use Flask only as a local UI layer. They do not replace the
board-side detector; `scripts/detect_web.py` starts `D` mode, parses `OVD1`
packets, converts frames to MJPEG, and exposes control endpoints that enqueue
single-byte firmware commands.

## Model Deployment Flow

```text
Edge Impulse Studio export
        |
        v
scripts/ei_deploy.sh
  - accepts Arduino Library or C++ MCU exports
  - installs/updates pill_counting_inferencing
  - validates input dimensions and tensor arena assumptions
        |
        v
nano_33/nano_33.ino
  - includes pill_counting_inferencing.h
  - compiles with EI_CLASSIFIER_ALLOCATION_STATIC
        |
        v
scripts/upload.sh
  - compiles for arduino:mbed_nano:nano33ble
  - parses dynamic memory usage
  - warns above 210 KB and fails above 220 KB by default
```

The current firmware assumes a 96x96 grayscale int8 Edge Impulse model. If the
model input shape or resize mode changes, update the firmware constants and
`ei_get_frame_data()` mapping before relying on runtime counts.

## Training Data Flow

```text
Board camera stream
        |
        +--> scripts/collect.sh
        |       -> docs/training_data/blister_0001.png
        |
        +--> scripts/collect_detect.sh
                -> docs/training_data/blister_0001.png
                -> docs/training_data/blister_0001.json
```

Captured images live under `docs/training_data/` using the existing
`blister_0001.png` naming convention. Detection-assisted captures may include
matching JSON metadata with board-side detections.

For local sanity checks, `scripts/test_training_data.py` builds a temporary C++
runner under `build/`, preprocesses training images with the same center-crop
and resize behavior as firmware, runs the installed Edge Impulse library, and
writes a CSV summary.

## Key Design Decisions

### Grayscale 160x120 Capture

Grayscale keeps the camera frame at 19,200 bytes. RGB565 would double that
buffer and make the Nano 33 BLE memory budget harder to satisfy alongside Mbed
OS and the TensorFlow Lite Micro arena.

### Signal Callback Instead of Resized Buffer

The firmware does not allocate a second 96x96 image. `ei_get_frame_data()`
converts requested model pixels from `g_frame` on demand. This saves RAM and
keeps preprocessing tied to Edge Impulse's expected signal interface.

### Board-Side Filtering

The board filters detections to the `blister` label and confidence threshold
before emitting counts or detection packets. Host tools can display results
without applying their own policy.

### Binary Packets for Live Views

Raw bytes avoid the overhead and parsing ambiguity of line-based frame output.
Magic values (`OVF1`, `OVD1`) let host tools resynchronize after debug text,
serial noise, or partial reads.

### JSON for Production Single-Shot Counts

The `J` command returns structured text for automation while avoiding large
frame transfers. This is the cleanest integration point for scripts that only
need the count and timing.

## Extension Points

- Add a new firmware command in `handleSerialCommands()` when the behavior must
  happen on the board.
- Add a new host viewer by reusing the existing packet layout and serial magic
  scanning patterns.
- Add model diagnostics to `printMemoryStatus()` when validating new Edge
  Impulse exports.
- Extend collectors only through `docs/training_data/` naming and metadata
  conventions so existing validation scripts keep working.
- Update `scripts/test_training_data.py` when the model input size, label set,
  or preprocessing changes.

## Operational Checks

Use these checks after architecture-affecting changes:

```bash
SKIP_UPLOAD=1 ./scripts/upload.sh
.venv/bin/python scripts/test_training_data.py --limit 10 --rebuild
./scripts/detect_web.sh
```

For hardware/model changes, record the board, serial port, model export, command
used, and observed output from `J`, `T`, `D`, or `M`.
