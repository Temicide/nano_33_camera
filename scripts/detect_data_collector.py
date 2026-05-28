#!/usr/bin/env python3
import argparse
import json
import queue
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import serial
from flask import Flask, Response, jsonify, render_template, request

MAGIC = b"OVD1"
BAUD_RATE = 921600
DET_STRUCT = struct.Struct("<HHHHH")
HEADER_STRUCT = struct.Struct("<HHBBIIH")
TRAINING_DIR = Path(__file__).resolve().parent.parent / "docs" / "training_data"

app = Flask(__name__)

state_lock = threading.Lock()
serial_lock = threading.Lock()
capture_file_lock = threading.Lock()
command_queue = queue.Queue()

serial_conn = None
latest_jpeg = None
latest_capture = None
capture_count = 0
latest_stats = {
    "connected": False,
    "ready": False,
    "frames": 0,
    "fps": 0.0,
    "count": 0,
    "detections": [],
    "frame_num": 0,
    "captured": 0,
    "last_capture": None,
    "last_error": "",
}


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
    skipped = bytearray()
    while len(buf) < len(MAGIC):
        b = ser.read(1)
        if not b:
            return None
        buf.append(b[0])

    while bytes(buf) != MAGIC:
        b = ser.read(1)
        if not b:
            return None
        skipped.append(buf.pop(0))
        buf.append(b[0])

    return bytes(skipped)


def read_packet(ser):
    skipped = scan_magic(ser)
    if skipped is None:
        return None

    header = ser.read(HEADER_STRUCT.size)
    if len(header) != HEADER_STRUCT.size:
        return None

    width, height, bpp, fmt, frame_num, frame_size, det_count = HEADER_STRUCT.unpack(
        header
    )
    if frame_size != width * height * bpp:
        return None

    detections = []
    for _ in range(det_count):
        raw = ser.read(DET_STRUCT.size)
        if len(raw) != DET_STRUCT.size:
            return None
        x, y, w, h, confidence = DET_STRUCT.unpack(raw)
        detections.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "confidence": confidence / 10000.0,
            }
        )

    frame_data = ser.read(frame_size)
    if len(frame_data) != frame_size:
        return None

    return {
        "width": width,
        "height": height,
        "bpp": bpp,
        "fmt": fmt,
        "frame_num": frame_num,
        "detections": detections,
        "frame_data": frame_data,
        "serial_text": skipped.decode("utf-8", errors="ignore"),
    }


def decode_gray(data, width, height, fmt):
    if fmt != 0:
        raise ValueError(f"Expected grayscale format 0, got {fmt}")
    return np.frombuffer(data, dtype=np.uint8).reshape((height, width)).copy()


def draw_overlay(gray, detections, fps, frame_num):
    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    for det in detections:
        x, y, w, h = det["x"], det["y"], det["w"], det["h"]
        conf = det["confidence"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (30, 230, 90), 1)
        cv2.putText(
            frame,
            f"{conf:.2f}",
            (x, max(9, y - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.32,
            (30, 230, 90),
            1,
            cv2.LINE_AA,
        )

    cv2.rectangle(frame, (0, 0), (159, 17), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"count {len(detections)}  fps {fps:.1f}  #{frame_num}",
        (4, 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.34,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return frame


def send_command(command):
    global serial_conn
    if serial_conn is None:
        return False
    with serial_lock:
        serial_conn.write(command)
    return True


def extract_serial_error(serial_text):
    for line in reversed(serial_text.splitlines()):
        line = line.strip()
        if "INFERENCE_ERROR" in line or line.startswith("ERR:"):
            return line
    return ""


def next_capture_index():
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    indices = []
    for path in TRAINING_DIR.glob("blister_*.png"):
        try:
            indices.append(int(path.stem.rsplit("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return max(indices, default=0) + 1


def existing_capture_count():
    if not TRAINING_DIR.exists():
        return 0
    return len(list(TRAINING_DIR.glob("blister_*.png")))


def serial_reader(port, baud):
    global latest_capture, latest_jpeg, serial_conn

    try:
        print(f"Connecting to {port} at {baud} baud...")
        ser = serial.Serial(port, baud, timeout=2.0)
        serial_conn = ser

        with state_lock:
            latest_stats["connected"] = True
            latest_stats["last_error"] = ""

        start = time.time()
        while time.time() - start < 10.0:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                print(f"  {line}")
            if "NANO33_OV7675_READY" in line:
                with state_lock:
                    latest_stats["ready"] = True
                break

        ser.reset_input_buffer()
        time.sleep(0.2)
        send_command(b"D")
        print("Board-side detection stream started")

        fps_start = time.time()
        fps_frames = 0
        fps = 0.0

        while True:
            while not command_queue.empty():
                send_command(command_queue.get_nowait())

            packet = read_packet(ser)
            if packet is None:
                continue

            serial_error = extract_serial_error(packet["serial_text"])
            gray = decode_gray(
                packet["frame_data"], packet["width"], packet["height"], packet["fmt"]
            )
            detections = packet["detections"]
            frame_num = packet["frame_num"]
            annotated = draw_overlay(gray, detections, fps, frame_num)
            display = cv2.resize(annotated, (640, 480), interpolation=cv2.INTER_NEAREST)
            ok, jpeg = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if not ok:
                continue

            fps_frames += 1
            now = time.time()
            if now - fps_start >= 1.0:
                fps = fps_frames / (now - fps_start)
                fps_start = now
                fps_frames = 0

            with state_lock:
                latest_jpeg = jpeg.tobytes()
                latest_capture = {
                    "gray": gray,
                    "width": packet["width"],
                    "height": packet["height"],
                    "frame_num": frame_num,
                    "pill_count": len(detections),
                    "detections": detections,
                }
                latest_stats["frames"] += 1
                latest_stats["fps"] = fps
                latest_stats["count"] = len(detections)
                latest_stats["detections"] = detections
                latest_stats["frame_num"] = frame_num
                latest_stats["last_error"] = serial_error
    except Exception as exc:
        with state_lock:
            latest_stats["connected"] = False
            latest_stats["last_error"] = str(exc)
        print(f"Serial reader failed: {exc}", file=sys.stderr)


def mjpeg_stream():
    while True:
        with state_lock:
            frame = latest_jpeg
        if frame is None:
            time.sleep(0.05)
            continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        time.sleep(0.02)


@app.route("/")
def index():
    return render_template("collect_detect.html")


@app.route("/stream")
def stream():
    return Response(mjpeg_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/stats")
def stats():
    with state_lock:
        return jsonify(dict(latest_stats))


@app.route("/count")
def count():
    with state_lock:
        return jsonify(
            {
                "captured": latest_stats["captured"],
                "frames": latest_stats["frames"],
                "live_count": latest_stats["count"],
                "frame_num": latest_stats["frame_num"],
            }
        )


@app.route("/capture", methods=["POST"])
def capture():
    global capture_count

    with state_lock:
        if latest_capture is None:
            return jsonify({"error": "No board detection frame available"}), 503
        snapshot = {
            "gray": latest_capture["gray"].copy(),
            "width": latest_capture["width"],
            "height": latest_capture["height"],
            "frame_num": latest_capture["frame_num"],
            "pill_count": latest_capture["pill_count"],
            "detections": list(latest_capture["detections"]),
        }

    with capture_file_lock:
        TRAINING_DIR.mkdir(parents=True, exist_ok=True)
        capture_count += 1
        filename = f"blister_{capture_count:04d}.png"
        json_filename = f"blister_{capture_count:04d}.json"
        image_path = TRAINING_DIR / filename
        json_path = TRAINING_DIR / json_filename

        if not cv2.imwrite(str(image_path), snapshot["gray"]):
            return jsonify({"error": f"Failed to write {image_path}"}), 500

        metadata = {
            "filename": filename,
            "json_filename": json_filename,
            "frame_num": snapshot["frame_num"],
            "pill_count": snapshot["pill_count"],
            "detections": snapshot["detections"],
            "width": snapshot["width"],
            "height": snapshot["height"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        json_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        saved_count = existing_capture_count()

    with state_lock:
        latest_stats["captured"] = saved_count
        latest_stats["last_capture"] = metadata

    return jsonify(
        {
            "filename": filename,
            "json_filename": json_filename,
            "path": str(image_path),
            "json_path": str(json_path),
            "count": saved_count,
            "pill_count": snapshot["pill_count"],
            "frame_num": snapshot["frame_num"],
            "detections": snapshot["detections"],
        }
    )


@app.route("/control", methods=["POST"])
def control():
    action = request.json.get("action", "")
    commands = {
        "auto": b"A",
        "face": b"F",
        "calibrated": b"c",
        "detect": b"D",
        "stop": b"X",
    }
    if action not in commands:
        return jsonify({"error": "unknown action"}), 400
    command_queue.put(commands[action])
    return jsonify({"ok": True, "action": action})


def main():
    parser = argparse.ArgumentParser(
        description="Board-side detection data collector for Nano 33 OV7675"
    )
    parser.add_argument("--port", "-p", help="Serial port")
    parser.add_argument("--baud", "-b", type=int, default=BAUD_RATE)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--web-port", "-w", type=int, default=5001)
    args = parser.parse_args()

    port = args.port or find_nano_port()
    if not port:
        print("Error: Could not find Arduino Nano 33. Specify --port.", file=sys.stderr)
        sys.exit(1)

    global capture_count
    capture_count = next_capture_index() - 1
    with state_lock:
        latest_stats["captured"] = existing_capture_count()

    thread = threading.Thread(target=serial_reader, args=(port, args.baud), daemon=True)
    thread.start()

    print(f"Board-side detection collector running at http://localhost:{args.web_port}")
    print(f"Saving PNG + JSON captures to: {TRAINING_DIR}")
    app.run(host=args.host, port=args.web_port, threaded=True)


if __name__ == "__main__":
    main()
