# Project Instructions

## Tech Stack
- Arduino Nano 33 BLE firmware in C++/Arduino (`nano_33/nano_33.ino`).
- OV7675 camera via `Arduino_OV767x`/TinyML Shield.
- Edge Impulse FOMO inference library named `pill_counting_inferencing`.
- Python tooling with `pyserial`, `opencv-python`, `numpy`, and `flask`.
- Shell scripts wrap `arduino-cli` and local Python tools.

## Code Style
- Arduino sketch uses 2-space indentation, `kName` constants, `g_name` globals, and lower camel case functions.
- Python scripts use 4-space indentation, `pathlib` where practical, `argparse`, and explicit `sys.exit` errors for missing hardware/config.
- Shell scripts should use `#!/usr/bin/env bash`, `set -euo pipefail`, and compute paths from `ROOT` or `SCRIPT_DIR`.
- Prefer structured JSON/CSV/binary parsing over ad hoc text parsing for serial packets and results.

## Testing
- Firmware compile check: `SKIP_UPLOAD=1 ./scripts/upload.sh`.
- Upload to board: `./scripts/upload.sh` or `PORT=/dev/cu.usbmodem1101 ./scripts/upload.sh`.
- Training-data model check: `.venv/bin/python scripts/test_training_data.py --limit 10 --rebuild`.
- Browser/OpenCV smoke tests: `./scripts/detect_web.sh`, `./scripts/live_view.sh`, or `./scripts/live_detect.sh`.
- For camera/model changes, record board, port, model export, command used, and observed serial output from commands such as `J`, `T`, `D`, or `M`.

## Build & Run
- Install board support: `arduino-cli core install arduino:mbed_nano`.
- Install Arduino camera libraries: `arduino-cli lib install "Arduino_OV767x" "TinyMLShield"`.
- Python setup: `python3 -m venv .venv && .venv/bin/pip install pyserial opencv-python numpy flask`.
- Detect port: `./scripts/port.sh`.
- Serial monitor: `./scripts/monitor.sh`.
- Detection web app: `./scripts/detect_web.sh` then open `http://localhost:5050`.
- Data collectors: `./scripts/collect.sh` and `./scripts/collect_detect.sh`.
- Deploy Edge Impulse export: `./scripts/ei_deploy.sh <export.zip>`.

## Project Structure
- `nano_33/nano_33.ino` - firmware for camera capture, exposure control, serial streaming, and Edge Impulse inference.
- `scripts/*.sh` - hardware command entrypoints for upload, monitor, viewers, collectors, and Edge Impulse setup.
- `scripts/*.py` - serial readers, browser/OpenCV viewers, calibration, collectors, and training-data checks.
- `scripts/templates/` - Flask UI templates for browser tools.
- `docs/training_data/` - captured `blister_0001.png` style images and matching JSON metadata.
- `docs/research/` - notes, experiments, and reports.
- `data/` - analysis CSVs.

## Runtime Protocol
- Firmware starts at 921600 baud and prints `NANO33_OV7675_READY`.
- Raw frames use binary magic `OVF1`; detection frames use `OVD1`.
- Key serial commands: `S` stream, `P` pause, `J` JSON count, `C` text count, `K` continuous count, `D` detection stream, `X` stop, `F` face exposure, `A` auto exposure, `c` calibrated exposure, `T` profile, `M` memory, `?` status.
- Detection code filters Edge Impulse bounding boxes to label `blister` with confidence at least `0.5`.

## Conventions
- Commit messages are short imperative subjects; conventional prefixes such as `docs:`, `chore:`, and `restructure:` appear in history.
- Keep generated/local files out of git: `build/`, `captures/`, `logs/`, `.venv/`, `compile_flags.txt`, and model-generated outputs.
- Use `PORT`, `FQBN`, and script arguments instead of hardcoding local device paths.
