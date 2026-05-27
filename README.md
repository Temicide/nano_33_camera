# Arduino Nano 33 in Cursor

Starter project for **Arduino Nano 33 BLE** or **Nano 33 IoT**, using `arduino-cli` from the terminal and the Arduino extension in Cursor.

## One-time setup (already done on this machine)

- `arduino-cli` installed via Homebrew
- Board cores: `arduino:mbed_nano` (BLE), `arduino:samd` (IoT)

## 1. Install the Cursor extension

1. Open this folder in Cursor: `File → Open Folder → nano_33`
2. When prompted, install **Arduino** (`vscode-arduino.vscode-arduino-community`)
3. Reload the window if needed

## 2. Connect the board

1. Plug the Nano 33 in with a **data** USB cable (not charge-only).
2. List ports:

```bash
arduino-cli board list
```

3. Copy the port (e.g. `/dev/cu.usbmodem1101`) into `.vscode/settings.json` → `"arduino.port"`.

### Pick your board (FQBN)

| Board           | Set in `settings.json`                          |
| --------------- | ----------------------------------------------- |
| Nano 33 **BLE** | `"arduino.fqbn": "arduino:mbed_nano:nano33ble"` |
| Nano 33 **IoT** | `"arduino.fqbn": "arduino:samd:nano_33_iot"`    |

**BLE upload tip:** Double-tap the reset button quickly if upload fails — the board enters the bootloader and shows a new port.

## 3. Build and upload

**From Cursor:** `Terminal → Run Task…` → **Arduino: Upload** (default build task: `Cmd+Shift+B`).

**From terminal:**

```bash
# BLE (default)
./scripts/upload.sh

# IoT
FQBN=arduino:samd:nano_33_iot ./scripts/upload.sh

# Explicit port
PORT=/dev/cu.usbmodem1101 ./scripts/upload.sh
```

**Serial monitor:**

```bash
./scripts/monitor.sh
```

The USB port name changes after upload or reset (e.g. `usbmodem314301` → `usbmodem114301`). If you see `command 'open' failed`, run `arduino-cli board list` and use the current port.

Or run task **Arduino: Serial Monitor** (after setting `arduino.port`).

## Live Camera View

The sketch streams OV7675 QCIF RGB565 frames from the TinyML Shield over USB serial.

```bash
./scripts/upload.sh
./scripts/live_view.sh
```

The viewer auto-detects the Nano 33 BLE port, leaves the board in **auto** mode (sensor-side AGC/AEC/AWB), serves the live feed at `http://127.0.0.1:8765/`, opens it in your browser, and decodes RGB565 as big-endian. By default it also applies a host-side trimmed gray-world white balance to clean up any residual color cast.

For a native OpenCV window instead, run:

```bash
./.venv/bin/python scripts/live_camera_view.py --port "$(./scripts/port.sh)"
```

### Camera modes

| Flag                    | Firmware command | Behavior                                                                      |
| ----------------------- | ---------------- | ----------------------------------------------------------------------------- |
| `--mode auto` (default) | `A`              | Sensor AGC/AEC + AWB run; SDE registers neutral                               |
| `--mode face`           | `F`              | Hand-tuned manual exposure/gain/saturation for close faces; **freezes AWB**   |
| `--mode stream`         | `S`              | Don't change mode; just start streaming whatever the firmware was last set to |

### Color pipeline flags

- `--no-white-balance` — disable host gray-world WB (raw sensor color).
- `--enhance` — opt in to luminance/chroma post-processing (`--gamma`, `--gain`, `--brightness`, `--saturation`, `--clahe`). All enhancement defaults are 1.0/0/off, so passing `--enhance` alone is a no-op until you set values.
- `--debug-color` — log per-channel BGR means and bias every `--debug-interval` frames; useful for confirming AWB convergence on a neutral target.
- `--byte-order {big,little}` — only change if you swap to a sensor that ships RGB565 as little-endian. The OV7675 is big-endian.

### White-balance calibration (software-only)

If `--mode auto` still leaves a cast under your specific lighting, capture a one-shot static WB:

```bash
mkdir -p captures
./.venv/bin/python scripts/live_camera_view.py \
    --mode auto --frames 60 --no-window \
    --no-white-balance --no-wb-file \
    --save-latest captures/wb_ref.png
./.venv/bin/python scripts/calibrate_wb.py captures/wb_ref.png
```

`calibrate_wb.py` writes `~/.config/nano33_wb.json`. The live viewer auto-loads it on startup (override with `--wb-file`, disable with `--no-wb-file`). Re-run whenever lighting changes meaningfully.

### Two RGB565 readers, two byte-order conventions

- `scripts/live_camera_view.py` reads the **binary wire stream** and treats each pixel as big-endian uint16.
- `scripts/4_2_12_ov7675imageviewer.py` reads `0xNNNN` **hex words** copied from the Arduino Serial Monitor and byte-swaps by default (the Serial Monitor prints word-order, not wire-order).

Don't feed one script's input to the other.

## Sketch

Edit `nano_33/nano_33.ino` — streams OV7675 camera frames at 176x144 RGB565 over USB serial.

## Troubleshooting

| Issue                    | Fix                                                           |
| ------------------------ | ------------------------------------------------------------- |
| No port in `board list`  | Try another cable/port; install board USB driver if Windows   |
| Upload timeout (BLE)     | Double-tap reset, re-run `board list`, update `arduino.port`  |
| Wrong board selected     | Match FQBN to your hardware (BLE vs IoT)                      |
| Extension can’t find CLI | `which arduino-cli` should be `/opt/homebrew/bin/arduino-cli` |
