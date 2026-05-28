#!/usr/bin/env python3
import argparse
import os
import struct
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import serial
from flask import Flask, Response, jsonify, render_template

MAGIC = b"OVF1"
BAUD_RATE = 921600
TRAINING_DIR = Path(__file__).resolve().parent.parent / "docs" / "training_data"

app = Flask(__name__)

latest_frame_lock = threading.Lock()
latest_raw_gray = None
latest_bgr = None
frame_count = 0
capture_count = 0


def find_nano_port():
    from serial.tools import list_ports

    for port in list_ports.comports():
        if "Nano 33" in port.description or "nano33ble" in port.device.lower():
            return port.device
        if "usbmodem" in port.device.lower():
            return port.device
    return None


def scan_magic(ser):
    buf = bytearray()
    while len(buf) < 4:
        b = ser.read(1)
        if not b:
            return False
        buf.append(b[0])
    while bytes(buf) != MAGIC:
        b = ser.read(1)
        if not b:
            return False
        buf.pop(0)
        buf.append(b[0])
    return True


def serial_reader(port, baud):
    global latest_raw_gray, latest_bgr, frame_count

    print(f"Connecting to {port} at {baud} baud...")
    ser = serial.Serial(port, baud, timeout=2.0)

    print("Waiting for Arduino ready signal...")
    ready_timeout = 10.0
    start_time = time.time()
    ready = False
    while time.time() - start_time < ready_timeout:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  {line}")
        if "NANO33_OV7675_READY" in line:
            ready = True
            break

    if not ready:
        print("Warning: Did not receive ready signal, continuing anyway...")

    ser.reset_input_buffer()
    time.sleep(0.1)

    ser.write(b"S")
    print("Streaming started")

    while True:
        if not scan_magic(ser):
            continue

        header = ser.read(14)
        if len(header) < 14:
            continue

        width, height, bpp, fmt, frame_num, frame_size = struct.unpack(
            "<HHBBII", header
        )

        expected_size = width * height * bpp
        if frame_size != expected_size:
            continue

        data = ser.read(frame_size)
        if len(data) < frame_size:
            continue

        with latest_frame_lock:
            if fmt in (0, 2):
                gray = np.frombuffer(data, dtype=np.uint8).reshape((height, width))
                latest_raw_gray = gray.copy()
                latest_bgr = cv2.cvtColor(latest_raw_gray, cv2.COLOR_GRAY2BGR)
            elif fmt == 1:
                pixels = np.frombuffer(data, dtype=">u2").astype(np.uint16)
                r = ((pixels >> 11) & 0x1F).astype(np.uint8)
                g = ((pixels >> 5) & 0x3F).astype(np.uint8)
                b = (pixels & 0x1F).astype(np.uint8)
                r = (r << 3) | (r >> 2)
                g = (g << 2) | (g >> 4)
                b = (b << 3) | (b >> 2)
                bgr = np.stack([b, g, r], axis=-1).reshape((height, width, 3))
                latest_bgr = bgr
                latest_raw_gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

            frame_count += 1


def generate_mjpeg():
    while True:
        with latest_frame_lock:
            if latest_bgr is None:
                time.sleep(0.05)
                continue
            display = cv2.resize(
                latest_bgr, (640, 480), interpolation=cv2.INTER_NEAREST
            )
            ret, jpeg = cv2.imencode(
                ".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )

        if not ret:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )
        time.sleep(0.05)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream")
def stream():
    return Response(
        generate_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/capture", methods=["POST"])
def capture():
    global capture_count

    with latest_frame_lock:
        if latest_raw_gray is None:
            return jsonify({"error": "No frame available"}), 503

        TRAINING_DIR.mkdir(parents=True, exist_ok=True)
        capture_count += 1
        filename = f"blister_{capture_count:04d}.png"
        filepath = TRAINING_DIR / filename
        cv2.imwrite(str(filepath), latest_raw_gray)

    return jsonify(
        {"filename": filename, "path": str(filepath), "count": capture_count}
    )


@app.route("/count")
def count():
    existing = (
        list(TRAINING_DIR.glob("blister_*.png")) if TRAINING_DIR.exists() else []
    )
    return jsonify({"captured": len(existing), "frames": frame_count})


def main():
    parser = argparse.ArgumentParser(
        description="Training data collector for Edge Impulse"
    )
    parser.add_argument("--port", "-p", help="Serial port (auto-detect if omitted)")
    parser.add_argument("--baud", "-b", type=int, default=BAUD_RATE)
    parser.add_argument("--host", default="0.0.0.0", help="Web server host")
    parser.add_argument(
        "--web-port", "-w", type=int, default=5000, help="Web server port"
    )
    args = parser.parse_args()

    port = args.port or find_nano_port()
    if not port:
        print(
            "Error: Could not find Arduino Nano 33. Specify --port or check USB connection.",
            file=sys.stderr,
        )
        sys.exit(1)

    global capture_count
    if TRAINING_DIR.exists():
        existing = list(TRAINING_DIR.glob("blister_*.png"))
        capture_count = len(existing)

    t = threading.Thread(target=serial_reader, args=(port, args.baud), daemon=True)
    t.start()

    print(f"\nCollector running at http://localhost:{args.web_port}")
    print(f"Saving to: {TRAINING_DIR}\n")

    app.run(host=args.host, port=args.web_port, threaded=True)


if __name__ == "__main__":
    main()
