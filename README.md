# nano_33 — Arduino Nano 33 BLE + OV7675 Camera

Arduino Nano 33 BLE project with OV7675 camera streaming and TinyML inference, using `arduino-cli` from the terminal.

## Branches

| Branch           | What it does                                                            |
| ---------------- | ----------------------------------------------------------------------- |
| `main`           | Base setup — board toolchain, upload scripts, serial monitor            |
| `grayscale`      | Live 160×120 grayscale camera stream over USB serial with Python viewer |
| `counting_model` | Edge Impulse FOMO model — medicine counting inference on-device         |

---

## Hardware

- **Arduino Nano 33 BLE** (nRF52840, Cortex-M4 @ 64 MHz, 256 KB RAM)
- **Arduino TinyML Shield** with **OV7675 camera** (up to 640×480)
- Data-capable USB cable (not charge-only)

---

## One-time Setup

### Arduino CLI

```bash
brew install arduino-cli
arduino-cli core install arduino:mbed_nano
arduino-cli lib install "Arduino_OV767x" "TinyMLShield"
```

### Python viewer (optional, needed for camera branches)

```bash
python3 -m venv .venv
.venv/bin/pip install pyserial opencv-python numpy
```

---

## Connect & Upload

1. Plug the Nano 33 in with a **data** USB cable.
2. Find your port:

```bash
arduino-cli board list
# or
./scripts/port.sh
```

3. Upload:

```bash
./scripts/upload.sh

# Explicit port
PORT=/dev/cu.usbmodem1101 ./scripts/upload.sh
```

4. Serial monitor:

```bash
./scripts/monitor.sh
```

**Upload tip (BLE):** If upload times out, double-tap the reset button — the board enters the bootloader and shows a new port. Re-run `board list` and update the port.

---

## Edge Impulse Model

Install the exported Edge Impulse model, then upload:

```bash
./scripts/ei_deploy.sh /Users/temicide/Downloads/pill-counting-cpp-mcu-v2-impulse-#1.zip
./scripts/upload.sh
```

The deploy script accepts either the Arduino Library export or the C++ MCU export and installs it as `pill_counting_inferencing`. The sketch includes `pill_counting_inferencing.h`.

Supported production profile:

- Camera capture: **160x120 grayscale** (`QQVGA`, 19,200 bytes)
- Model input: **96x96 grayscale int8**
- Edge Impulse arena: target **<=120 KB**, rejected above **140 KB**
- Upload builds define `EI_CLASSIFIER_ALLOCATION_STATIC` so tensor arena RAM is visible in the compile report instead of being hidden as a runtime heap allocation.

Serial commands after upload:

| Command | Action                    |
| ------- | ------------------------- |
| `J`     | Production single-shot JSON count |
| `C`     | Capture one frame + count |
| `M`     | Print memory diagnostics  |
| `T`     | Print capture/inference timing profile |
| `K`     | Continuous counting       |
| `D`     | Live detection stream     |
| `X`     | Stop continuous counting  |
| `S`     | Start camera streaming    |
| `P`     | Pause camera streaming    |

Use `J` for the production workflow. It captures one 160x120 grayscale frame,
runs the 96x96 FOMO model once, and returns one JSON line with `ok`, `count`,
`boxes`, and `timing_ms`. It does not send image bytes.

Run the browser-based bounding-box viewer after uploading the model firmware:

```bash
./scripts/detect_web.sh
```

Open http://localhost:5050. The page displays the grayscale camera feed with `blister` boxes, count, FPS, and exposure controls.

---

## Scripts

| Script                 | Purpose                                      |
| ---------------------- | -------------------------------------------- |
| `scripts/upload.sh`    | Compile and flash via `arduino-cli`          |
| `scripts/monitor.sh`   | Open serial monitor at 921600 baud           |
| `scripts/port.sh`      | Auto-detect and print the Nano 33 port       |
| `scripts/live_view.sh` | Launch live camera viewer (grayscale branch) |
| `scripts/live_detect.sh` | Launch model detection viewer with boxes   |
| `scripts/detect_web.sh` | Launch browser detection app with boxes    |

---

## Project Structure

```
nano_33/
├── nano_33/nano_33.ino       # Main Arduino sketch
├── scripts/                  # Shell + Python helper scripts
├── docs/research/            # Research notes and design specs
└── .gitignore
```

---

## Troubleshooting

| Issue                    | Fix                                                       |
| ------------------------ | --------------------------------------------------------- |
| No port in `board list`  | Try another cable; use a data-capable USB cable           |
| Upload timeout (BLE)     | Double-tap reset button, re-run `board list`, update port |
| Wrong board selected     | FQBN: `arduino:mbed_nano:nano33ble`                       |
| Extension can't find CLI | `which arduino-cli` → `/opt/homebrew/bin/arduino-cli`     |
