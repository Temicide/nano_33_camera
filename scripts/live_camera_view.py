#!/usr/bin/env python3
import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import serial

MAGIC = b"OVF1"
BAUD_RATE = 921600
DEFAULT_WB_FILE = Path.home() / ".config" / "nano33_wb.json"


def find_nano_port():
    from serial.tools import list_ports

    for port in list_ports.comports():
        if "Nano 33" in port.description or "nano33ble" in port.device.lower():
            return port.device
        if "usbmodem" in port.device.lower():
            return port.device
    return None


def rgb565_to_bgr(data, width, height, byte_order="big"):
    if byte_order == "big":
        pixels = np.frombuffer(data, dtype=">u2").astype(np.uint16)
    else:
        pixels = np.frombuffer(data, dtype="<u2").astype(np.uint16)

    r = ((pixels >> 11) & 0x1F).astype(np.uint8)
    g = ((pixels >> 5) & 0x3F).astype(np.uint8)
    b = (pixels & 0x1F).astype(np.uint8)

    r = (r << 3) | (r >> 2)
    g = (g << 2) | (g >> 4)
    b = (b << 3) | (b >> 2)

    bgr = np.stack([b, g, r], axis=-1).reshape((height, width, 3))
    return bgr


def apply_gray_world_wb(frame, gains=None):
    if gains:
        frame = frame.astype(np.float32)
        frame[:, :, 0] *= gains.get("b", 1.0)
        frame[:, :, 1] *= gains.get("g", 1.0)
        frame[:, :, 2] *= gains.get("r", 1.0)
        return np.clip(frame, 0, 255).astype(np.uint8)

    mean_b = np.mean(frame[:, :, 0])
    mean_g = np.mean(frame[:, :, 1])
    mean_r = np.mean(frame[:, :, 2])
    mean_gray = (mean_b + mean_g + mean_r) / 3.0

    if mean_b > 0:
        frame[:, :, 0] = np.clip(frame[:, :, 0] * (mean_gray / mean_b), 0, 255)
    if mean_g > 0:
        frame[:, :, 1] = np.clip(frame[:, :, 1] * (mean_gray / mean_g), 0, 255)
    if mean_r > 0:
        frame[:, :, 2] = np.clip(frame[:, :, 2] * (mean_gray / mean_r), 0, 255)

    return frame.astype(np.uint8)


def apply_enhancements(
    frame, gamma=1.0, gain=1.0, brightness=0, saturation=1.0, clahe_clip=0
):
    if gamma != 1.0:
        inv_gamma = 1.0 / gamma
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255 for i in np.arange(256)]
        ).astype("uint8")
        frame = cv2.LUT(frame, table)

    if gain != 1.0 or brightness != 0:
        frame = cv2.convertScaleAbs(frame, alpha=gain, beta=brightness)

    if saturation != 1.0:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
        frame = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    if clahe_clip > 0:
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
        l = clahe.apply(l)
        frame = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

    return frame


def load_wb_file(path):
    if path and path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load WB file {path}: {e}", file=sys.stderr)
    return None


def main():
    parser = argparse.ArgumentParser(description="Live camera viewer for Arduino Nano 33 OV7675")
    parser.add_argument("--port", "-p", help="Serial port (auto-detect if not specified)")
    parser.add_argument("--baud", "-b", type=int, default=BAUD_RATE, help=f"Baud rate (default: {BAUD_RATE})")
    parser.add_argument("--mode", "-m", choices=["auto", "face", "calibrated", "stream"], default="auto",
                        help="Camera exposure mode (default: auto)")
    parser.add_argument("--byte-order", choices=["big", "little"], default="big",
                        help="RGB565 byte order (default: big)")
    parser.add_argument("--no-white-balance", action="store_true", help="Disable host gray-world white balance")
    parser.add_argument("--wb-file", type=Path, default=DEFAULT_WB_FILE,
                        help=f"White balance calibration file (default: {DEFAULT_WB_FILE})")
    parser.add_argument("--no-wb-file", action="store_true", help="Disable loading WB calibration file")
    parser.add_argument("--enhance", action="store_true", help="Enable image enhancement")
    parser.add_argument("--gamma", type=float, default=1.0, help="Gamma correction (default: 1.0)")
    parser.add_argument("--gain", type=float, default=1.0, help="Gain multiplier (default: 1.0)")
    parser.add_argument("--brightness", type=int, default=0, help="Brightness offset (default: 0)")
    parser.add_argument("--saturation", type=float, default=1.0, help="Saturation multiplier (default: 1.0)")
    parser.add_argument("--clahe", type=float, default=0, help="CLAHE clip limit (default: 0 = disabled)")
    parser.add_argument("--debug-color", action="store_true", help="Log per-channel BGR means")
    parser.add_argument("--debug-interval", type=int, default=30, help="Debug log interval in frames (default: 30)")
    parser.add_argument("--save-latest", type=Path, help="Save latest frame to this path")
    parser.add_argument("--frames", type=int, default=0, help="Exit after N frames (0 = run forever)")
    parser.add_argument("--no-window", action="store_true", help="Don't show OpenCV window")
    parser.add_argument("--window-name", default="OV7675 Live", help="Window title")

    args = parser.parse_args()

    port = args.port or find_nano_port()
    if not port:
        print("Error: Could not find Arduino Nano 33. Specify --port or check USB connection.", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to {port} at {args.baud} baud...")
    ser = serial.Serial(port, args.baud, timeout=2.0)
    
    print("Waiting for Arduino ready signal...")
    ready_timeout = 10.0
    start_time = time.time()
    ready = False
    while time.time() - start_time < ready_timeout:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if line:
            print(f"  {line}")
        if "NANO33_OV7675_READY" in line:
            ready = True
            break
    
    if not ready:
        print("Warning: Did not receive ready signal, continuing anyway...", file=sys.stderr)
    
    ser.reset_input_buffer()
    time.sleep(0.1)

    mode_cmd = {"auto": b"A", "face": b"F", "calibrated": b"C", "stream": b"S"}
    if args.mode in mode_cmd:
        ser.write(mode_cmd[args.mode])
        print(f"Sent mode command: {args.mode}")
        time.sleep(0.1)
        ser.reset_input_buffer()

    ser.write(b"S")
    print("Streaming started")

    wb_gains = None
    if not args.no_wb_file:
        wb_gains = load_wb_file(args.wb_file)
        if wb_gains:
            print(f"Loaded WB calibration from {args.wb_file}")

    if not args.no_window:
        cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)

    frame_count = 0
    fps_start = time.time()
    fps_count = 0

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

    try:
        while True:
            if not scan_magic(ser):
                continue

            header = ser.read(14)
            if len(header) < 14:
                continue

            width, height, bpp, fmt, frame_num, frame_size = struct.unpack("<HHBBII", header)

            if bpp != 2 or frame_size != width * height * 2:
                continue

            data = ser.read(frame_size)
            if len(data) < frame_size:
                continue

            frame = rgb565_to_bgr(data, width, height, args.byte_order)

            if not args.no_white_balance:
                frame = apply_gray_world_wb(frame, wb_gains)

            if args.enhance:
                frame = apply_enhancements(
                    frame, args.gamma, args.gain, args.brightness, args.saturation, args.clahe
                )

            if args.debug_color and frame_count % args.debug_interval == 0:
                mean_b = np.mean(frame[:, :, 0])
                mean_g = np.mean(frame[:, :, 1])
                mean_r = np.mean(frame[:, :, 2])
                print(f"Frame {frame_count}: B={mean_b:.1f} G={mean_g:.1f} R={mean_r:.1f}")

            if args.save_latest:
                args.save_latest.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(args.save_latest), frame)

            if not args.no_window:
                cv2.imshow(args.window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    break
                elif key == ord("s"):
                    ser.write(b"S")
                elif key == ord("p"):
                    ser.write(b"P")
                elif key == ord("a"):
                    ser.write(b"A")
                elif key == ord("f"):
                    ser.write(b"F")
                elif key == ord("c"):
                    ser.write(b"C")

            frame_count += 1
            fps_count += 1

            if time.time() - fps_start >= 1.0:
                fps = fps_count / (time.time() - fps_start)
                if not args.no_window:
                    cv2.setWindowTitle(args.window_name, f"{args.window_name} - {fps:.1f} FPS")
                fps_start = time.time()
                fps_count = 0

            if args.frames > 0 and frame_count >= args.frames:
                break

    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        ser.write(b"P")
        ser.close()
        if not args.no_window:
            cv2.destroyAllWindows()
        print(f"Captured {frame_count} frames")


if __name__ == "__main__":
    main()
