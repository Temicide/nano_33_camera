#!/usr/bin/env python3
import argparse
import struct
import sys
import time

import cv2
import numpy as np
import serial

MAGIC = b"OVD1"
BAUD_RATE = 921600
DET_STRUCT = struct.Struct("<HHHHH")
HEADER_STRUCT = struct.Struct("<HHBBIIH")


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


def decode_frame(data, width, height, fmt):
    if fmt != 0:
        raise ValueError(f"Expected grayscale format 0, got {fmt}")
    gray = np.frombuffer(data, dtype=np.uint8).reshape((height, width))
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def read_packet(ser):
    if not scan_magic(ser):
        return None

    header = ser.read(HEADER_STRUCT.size)
    if len(header) != HEADER_STRUCT.size:
        return None

    width, height, bpp, fmt, frame_num, frame_size, det_count = HEADER_STRUCT.unpack(header)
    expected_size = width * height * bpp
    if frame_size != expected_size:
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

    return width, height, fmt, frame_num, detections, frame_data


def draw_overlay(frame, detections, frame_num, fps):
    for det in detections:
        x = det["x"]
        y = det["y"]
        w = det["w"]
        h = det["h"]
        conf = det["confidence"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 1)
        label = f"blister {conf:.2f}"
        cv2.putText(
            frame,
            label,
            (x, max(0, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            (0, 255, 0),
            1,
            cv2.LINE_AA,
        )

    cv2.putText(
        frame,
        f"count={len(detections)} frame={frame_num} fps={fps:.1f}",
        (4, 14),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return frame


def main():
    parser = argparse.ArgumentParser(
        description="Real-time Edge Impulse object detection viewer for Nano 33 OV7675"
    )
    parser.add_argument("--port", "-p", help="Serial port")
    parser.add_argument("--baud", "-b", type=int, default=BAUD_RATE)
    parser.add_argument(
        "--mode",
        "-m",
        choices=["auto", "face", "calibrated", "stream"],
        default="auto",
        help="Camera exposure mode before detection starts",
    )
    parser.add_argument("--scale", type=int, default=4, help="Display scale factor")
    parser.add_argument("--frames", type=int, default=0, help="Exit after N frames")
    parser.add_argument("--no-window", action="store_true")
    parser.add_argument("--save-latest", help="Path to save the latest annotated frame")
    parser.add_argument("--window-name", default="Nano 33 Detection")
    args = parser.parse_args()

    port = args.port or find_nano_port()
    if not port:
        print("Error: Could not find Arduino Nano 33. Specify --port.", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {port} at {args.baud} baud...")
    ser = serial.Serial(port, args.baud, timeout=2.0)

    start = time.time()
    while time.time() - start < 10.0:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line:
            print(f"  {line}")
        if "NANO33_OV7675_READY" in line:
            break

    ser.reset_input_buffer()
    mode_cmd = {"auto": b"A", "face": b"F", "calibrated": b"c", "stream": b""}
    if mode_cmd[args.mode]:
        ser.write(mode_cmd[args.mode])
        time.sleep(0.2)
        ser.reset_input_buffer()

    ser.write(b"D")
    time.sleep(0.2)
    ser.reset_input_buffer()
    print("Detection stream started. Press q or Esc to quit.")

    if not args.no_window:
        cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)

    frame_count = 0
    fps = 0.0
    fps_start = time.time()
    fps_frames = 0

    try:
        while True:
            packet = read_packet(ser)
            if packet is None:
                continue

            width, height, fmt, frame_num, detections, frame_data = packet
            frame = decode_frame(frame_data, width, height, fmt)
            frame = draw_overlay(frame, detections, frame_num, fps)

            if args.save_latest:
                cv2.imwrite(args.save_latest, frame)

            if not args.no_window:
                display = cv2.resize(
                    frame,
                    (width * args.scale, height * args.scale),
                    interpolation=cv2.INTER_NEAREST,
                )
                cv2.imshow(args.window_name, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("a"):
                    ser.write(b"A")
                elif key == ord("f"):
                    ser.write(b"F")
                elif key == ord("c"):
                    ser.write(b"c")

            frame_count += 1
            fps_frames += 1
            now = time.time()
            if now - fps_start >= 1.0:
                fps = fps_frames / (now - fps_start)
                print(f"fps={fps:.1f} count={len(detections)}")
                fps_start = now
                fps_frames = 0

            if args.frames and frame_count >= args.frames:
                break
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        ser.write(b"X")
        ser.close()
        if not args.no_window:
            cv2.destroyAllWindows()
        print(f"Processed {frame_count} detection frames")


if __name__ == "__main__":
    main()
