#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

DEFAULT_WB_FILE = Path.home() / ".config" / "nano33_wb.json"


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate white balance from a reference image of a neutral target"
    )
    parser.add_argument("image", type=Path, help="Reference image (e.g., white/gray card)")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_WB_FILE,
        help=f"Output WB calibration file (default: {DEFAULT_WB_FILE})",
    )
    parser.add_argument(
        "--roi",
        type=int,
        nargs=4,
        metavar=("X", "Y", "W", "H"),
        help="Region of interest (x y width height) for calibration",
    )

    args = parser.parse_args()

    if not args.image.exists():
        print(f"Error: Image not found: {args.image}", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(str(args.image))
    if img is None:
        print(f"Error: Could not read image: {args.image}", file=sys.stderr)
        sys.exit(1)

    if args.roi:
        x, y, w, h = args.roi
        roi = img[y : y + h, x : x + w]
    else:
        h, w = img.shape[:2]
        margin_x, margin_y = w // 4, h // 4
        roi = img[margin_y : h - margin_y, margin_x : w - margin_x]

    mean_b = np.mean(roi[:, :, 0])
    mean_g = np.mean(roi[:, :, 1])
    mean_r = np.mean(roi[:, :, 2])
    mean_gray = (mean_b + mean_g + mean_r) / 3.0

    gains = {
        "b": float(mean_gray / mean_b) if mean_b > 0 else 1.0,
        "g": float(mean_gray / mean_g) if mean_g > 0 else 1.0,
        "r": float(mean_gray / mean_r) if mean_r > 0 else 1.0,
    }

    print(f"Reference image: {args.image}")
    print(f"ROI means: B={mean_b:.1f} G={mean_g:.1f} R={mean_r:.1f}")
    print(f"Computed gains: B={gains['b']:.3f} G={gains['g']:.3f} R={gains['r']:.3f}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(gains, f, indent=2)

    print(f"Saved calibration to {args.output}")


if __name__ == "__main__":
    main()
