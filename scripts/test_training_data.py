#!/usr/bin/env python3
import argparse
import csv
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "build" / "ei_training_data_runner"
BUILD_DIR = ROOT / "build" / "ei_training_data_runner.d"
EI_LIB = Path.home() / "Documents" / "Arduino" / "libraries" / "pill_counting_inferencing"
EI_SRC = EI_LIB / "src"


RUNNER_SOURCE = r'''
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "pill_counting_inferencing.h"

static std::vector<float> g_features;

int get_signal_data(size_t offset, size_t length, float *out_ptr) {
    if (offset + length > g_features.size()) {
        return -1;
    }
    for (size_t ix = 0; ix < length; ix++) {
        out_ptr[ix] = g_features[offset + ix];
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        std::cerr << "usage: " << argv[0] << " <features.f32>" << std::endl;
        return 2;
    }

    std::ifstream input(argv[1], std::ios::binary);
    if (!input) {
        std::cerr << "could not open " << argv[1] << std::endl;
        return 2;
    }

    g_features.assign(EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE, 0.0f);
    input.read(reinterpret_cast<char *>(g_features.data()),
               g_features.size() * sizeof(float));
    if (input.gcount() != static_cast<std::streamsize>(g_features.size() * sizeof(float))) {
        std::cerr << "feature file has wrong size" << std::endl;
        return 2;
    }

    signal_t signal;
    signal.total_length = EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE;
    signal.get_data = &get_signal_data;

    ei_impulse_result_t result = {};
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    if (err != EI_IMPULSE_OK) {
        std::cerr << "run_classifier failed: " << err << std::endl;
        return 1;
    }

    std::cout << "{\"boxes\":[";
    for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
        const auto &bb = result.bounding_boxes[i];
        if (i != 0) {
            std::cout << ",";
        }
        std::cout << "{\"label\":\"" << bb.label << "\",\"value\":" << bb.value
                  << ",\"x\":" << bb.x << ",\"y\":" << bb.y
                  << ",\"w\":" << bb.width << ",\"h\":" << bb.height << "}";
    }
    std::cout << "]}" << std::endl;
    return 0;
}
'''


def run(cmd):
    subprocess.run(cmd, check=True, cwd=ROOT)


def build_runner():
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    src = BUILD_DIR / "runner.cpp"
    src.write_text(RUNNER_SOURCE)

    include_flags = [
        f"-I{EI_SRC}",
        f"-I{EI_SRC / 'edge-impulse-sdk'}",
        f"-I{EI_SRC / 'edge-impulse-sdk' / 'CMSIS' / 'DSP' / 'Include'}",
        f"-I{EI_SRC / 'edge-impulse-sdk' / 'CMSIS' / 'Core' / 'Include'}",
    ]
    defines = [
        "-DEI_PORTING_POSIX=1",
        "-DEI_PORTING_MBED=0",
        "-DEI_CLASSIFIER_ALLOCATION_STATIC=0",
    ]

    sources = [
        src,
        EI_SRC / "tflite-model" / "tflite_learn_1011420_3_compiled.cpp",
        EI_SRC / "edge-impulse-sdk" / "classifier" / "ei_run_classifier_c.cpp",
        EI_SRC / "edge-impulse-sdk" / "dsp" / "memory.cpp",
        EI_SRC / "edge-impulse-sdk" / "dsp" / "image" / "processing.cpp",
        EI_SRC / "edge-impulse-sdk" / "dsp" / "kissfft" / "kiss_fft.cpp",
        EI_SRC / "edge-impulse-sdk" / "dsp" / "kissfft" / "kiss_fftr.cpp",
        EI_SRC / "edge-impulse-sdk" / "porting" / "posix" / "ei_classifier_porting.cpp",
        EI_SRC / "edge-impulse-sdk" / "porting" / "posix" / "debug_log.cpp",
    ]
    sources += sorted((EI_SRC / "edge-impulse-sdk" / "tensorflow" / "lite").rglob("*.cc"))

    cmd = [
        "c++",
        "-std=c++17",
        "-O2",
        "-Wno-unused-function",
        "-Wno-unused-variable",
        "-Wno-deprecated-declarations",
        *defines,
        *include_flags,
        *map(str, sources),
        "-o",
        str(RUNNER),
    ]
    run(cmd)


def preprocess(path):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise RuntimeError(f"could not load {path}")

    height, width = img.shape
    infer_w = infer_h = 96
    frame_aspect = width * infer_h
    infer_aspect = infer_w * height
    if frame_aspect > infer_aspect:
        source_w = (height * infer_w) // infer_h
        source_h = height
    else:
        source_w = width
        source_h = (width * infer_h) // infer_w

    source_x = (width - source_w) // 2
    source_y = (height - source_h) // 2
    crop = img[source_y : source_y + source_h, source_x : source_x + source_w]
    resized = cv2.resize(crop, (infer_w, infer_h), interpolation=cv2.INTER_AREA)

    gray = resized.astype(np.uint32)
    rgb_packed = ((gray << 16) | (gray << 8) | gray).astype(np.float32)
    return rgb_packed.reshape(-1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(ROOT / "docs" / "training_data"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "build" / "training_data_model_results.csv"))
    args = parser.parse_args()

    if args.rebuild or not RUNNER.exists():
        build_runner()

    data_dir = Path(args.data)
    images = sorted(data_dir.glob("*.png"))
    if args.limit:
        images = images[: args.limit]

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    temp_features = BUILD_DIR / "features.f32"
    for image_path in images:
        features = preprocess(image_path)
        features.tofile(temp_features)
        proc = subprocess.run(
            [str(RUNNER), str(temp_features)],
            check=True,
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        result = json.loads(proc.stdout)
        boxes = [b for b in result["boxes"] if b["label"] == "blister"]
        rows.append(
            {
                "image": str(image_path),
                "count": len(boxes),
                "max_confidence": max((b["value"] for b in boxes), default=0.0),
                "boxes": json.dumps(boxes),
            }
        )

    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["image", "count", "max_confidence", "boxes"])
        writer.writeheader()
        writer.writerows(rows)

    detected = sum(1 for row in rows if row["count"] > 0)
    total_boxes = sum(int(row["count"]) for row in rows)
    print(f"images={len(rows)} detected_images={detected} total_boxes={total_boxes}")
    if rows:
        counts = np.array([int(row["count"]) for row in rows])
        confidences = np.array([float(row["max_confidence"]) for row in rows])
        print(f"count_min={counts.min()} count_max={counts.max()} count_mean={counts.mean():.2f}")
        print(f"max_conf_min={confidences.min():.3f} max_conf_max={confidences.max():.3f} max_conf_mean={confidences.mean():.3f}")
    print(f"wrote={output_path}")


if __name__ == "__main__":
    main()
