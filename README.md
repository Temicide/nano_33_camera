# Nano 33 Medicine Counting

Arduino Nano 33 BLE + OV7675 camera project for counting medicine blister cells on-device with an Edge Impulse FOMO object-detection model. The firmware captures 160x120 grayscale frames, crops/resizes them to the model's 96x96 input, and streams either raw frames, detection frames, or JSON count results over USB serial.

## Hardware

- Arduino Nano 33 BLE (`arduino:mbed_nano:nano33ble`)
- Arduino TinyML Shield with OV7675 camera
- Data-capable USB cable

## Repository Layout

```text
nano_33/
├── nano_33/nano_33.ino       # Firmware: camera capture, Edge Impulse inference, serial protocol
├── scripts/                  # Upload, monitor, viewers, collectors, calibration, model checks
├── scripts/templates/        # Flask UI templates for browser tools
├── docs/training_data/       # Captured blister images and board-detection metadata
├── docs/research/            # Research notes, experiments, and reports
└── data/                     # Analysis CSVs
```

Generated files such as `build/`, `captures/`, `logs/`, `.venv/`, and `compile_flags.txt` are intentionally ignored.

For a deeper explanation of the firmware, serial protocol, host tools, and data
flow, see [docs/architecture.md](docs/architecture.md).

## Setup

Install the Arduino toolchain and board support:

```bash
brew install arduino-cli
arduino-cli core install arduino:mbed_nano
arduino-cli lib install "Arduino_OV767x" "TinyMLShield"
```

Create the Python environment used by the viewers and data tools:

```bash
python3 -m venv .venv
.venv/bin/pip install pyserial opencv-python numpy flask
```

Optional: install the Edge Impulse CLI if you want to connect the board directly to Edge Impulse Studio with `./scripts/ei_connect.sh`.

## Edge Impulse Model

The firmware expects a library named `pill_counting_inferencing` and includes `pill_counting_inferencing.h`. Install or replace the exported model with:

```bash
./scripts/ei_deploy.sh ~/Downloads/pill-counting-cpp-mcu.zip
```

The deploy script accepts Arduino Library and C++ MCU exports. It validates the model against the firmware assumptions:

- input: 96x96 grayscale
- input type: int8
- tensor arena target: <=120 KB
- tensor arena hard limit: <=140 KB

## Build and Upload

Plug in the board, then detect its serial port:

```bash
./scripts/port.sh
```

Compile without flashing:

```bash
SKIP_UPLOAD=1 ./scripts/upload.sh
```

Compile and upload:

```bash
./scripts/upload.sh
```

Override the detected port when needed:

```bash
PORT=/dev/cu.usbmodem1101 ./scripts/upload.sh
```

`scripts/upload.sh` compiles with `EI_CLASSIFIER_ALLOCATION_STATIC`, reports dynamic memory use, warns above 210 KB, and fails above 220 KB by default. If upload times out, double-tap the Nano 33 reset button to enter the bootloader, rerun `arduino-cli board list`, and upload again.

## Run the Project

Open the serial monitor:

```bash
./scripts/monitor.sh
```

Start the browser detection app:

```bash
./scripts/detect_web.sh
```

Open <http://localhost:5050>. The app shows the grayscale feed, board-side `blister` boxes, count, FPS, and exposure controls.

Other local tools:

```bash
./scripts/live_view.sh        # OpenCV live camera viewer
./scripts/live_detect.sh      # OpenCV detection viewer with boxes
./scripts/collect.sh          # Browser image collector at http://localhost:5000
./scripts/collect_detect.sh   # Detection-assisted collector at http://localhost:5001
```

Training captures are saved to `docs/training_data/` as `blister_0001.png` style files. The detection-assisted collector also writes matching JSON metadata.

## Serial Commands

The firmware prints `NANO33_OV7675_READY` at startup and accepts single-character commands at 921600 baud:

| Command | Action |
| --- | --- |
| `S` | Start raw frame streaming |
| `P` | Pause streaming |
| `J` | Production single-shot JSON count |
| `C` | Single count with text output |
| `K` | Continuous count mode |
| `D` | Detection stream with frame bytes and boxes |
| `X` | Stop count or detection mode |
| `F` | Apply face/exposure preset |
| `A` | Return to auto exposure |
| `c` | Apply calibrated exposure preset |
| `T` | Print capture/inference timing profile |
| `M` | Print memory/model diagnostics |
| `?` | Reprint status and command help |

Use `J` for production-style count checks. It captures one frame, runs inference once, and returns a JSON line with fields such as `ok`, `count`, `boxes`, and `timing_ms`.

## Model and Data Checks

When the Edge Impulse library is installed, validate sample training images with:

```bash
.venv/bin/python scripts/test_training_data.py --limit 10 --rebuild
```

This builds a local C++ classifier runner under `build/`, preprocesses `docs/training_data/*.png` the same way as firmware, and writes a CSV summary.

## Troubleshooting

| Issue | Fix |
| --- | --- |
| `No Nano 33 USB port found` | Use a data-capable cable and run `arduino-cli board list`. |
| Upload timeout | Double-tap reset, select the bootloader port, and rerun upload. |
| Missing model header | Run `./scripts/ei_deploy.sh <export.zip>` and confirm the installed Arduino library is `pill_counting_inferencing`. |
| Browser tool cannot connect | Confirm no serial monitor is holding the port, then pass `PORT=/dev/cu...` to the script. |
| RAM limit failure | Re-export a smaller Edge Impulse model, for example with EON RAM optimized settings or a smaller FOMO backbone. |
