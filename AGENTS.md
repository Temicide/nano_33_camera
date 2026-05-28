# Repository Guidelines

## Project Structure & Module Organization

- `nano_33/nano_33.ino` is the main Arduino Nano 33 BLE sketch for OV7675 capture, serial streaming, and Edge Impulse inference.
- `scripts/` contains shell entrypoints and Python tools for upload, monitoring, camera viewing, detection, calibration, and training-data checks. Static browser templates live in `scripts/templates/`.
- `docs/training_data/` stores captured blister images and annotation JSON files. Keep names in the existing `blister_0001.png` style.
- `docs/research/` contains design notes, experiments, and reports. `data/` holds analysis CSVs.
- Generated or local-only files belong in ignored paths such as `build/`, `captures/`, `logs/`, `.venv/`, and `compile_flags.txt`.

## Build, Test, and Development Commands

- `arduino-cli core install arduino:mbed_nano` and `arduino-cli lib install "Arduino_OV767x" "TinyMLShield"` install board support and camera libraries.
- `python3 -m venv .venv && .venv/bin/pip install pyserial opencv-python numpy` prepares the viewer and data tools.
- `./scripts/port.sh` prints the detected Nano 33 serial port.
- `SKIP_UPLOAD=1 ./scripts/upload.sh` compiles without flashing; use this before firmware PRs.
- `./scripts/upload.sh` compiles and uploads to `arduino:mbed_nano:nano33ble`; override with `PORT=/dev/cu.usbmodem1101`.
- `./scripts/monitor.sh`, `./scripts/live_view.sh`, `./scripts/live_detect.sh`, and `./scripts/detect_web.sh` run serial monitoring and visual viewers.
- `.venv/bin/python scripts/test_training_data.py --limit 10 --rebuild` validates model behavior against sample training images when the Edge Impulse library is installed.

## Coding Style & Naming Conventions

Use 2-space indentation in the Arduino sketch and 4-space indentation in Python. Follow existing C++ names: `kName` for constants, `g_name` for globals, and lower camel case for functions. Shell scripts should use `#!/usr/bin/env bash`, `set -euo pipefail`, and compute paths from `ROOT`. Python tools should prefer `pathlib`, `argparse`, structured JSON/CSV APIs, and explicit errors over silent fallbacks.

## Testing Guidelines

There is no standalone unit-test suite. Treat compile-only firmware builds, viewer smoke tests, and `scripts/test_training_data.py` as the project checks. For camera or model changes, record the exact board, port, model export, command used, and observed serial command output such as `J`, `T`, or `D`.

## Commit & Pull Request Guidelines

History uses concise imperative subjects, sometimes with conventional prefixes such as `chore:`, `docs:`, or `restructure:`. Keep that style, for example `docs: add calibration notes` or `Add detection viewer controls`. PRs should describe hardware/model assumptions, list verification commands, link related notes or issues, and include screenshots for browser viewer changes.

## Security & Configuration Tips

Do not commit local machine paths, generated captures, build outputs, logs, virtual environments, or exported model zips. Prefer `PORT`, `FQBN`, and script arguments over hardcoded device paths.
