# Medicine Counting with FOMO — Design Spec

**Date:** 2026-05-27
**Target:** Arduino Nano 33 BLE Sense + OV7675 (TinyML Shield)
**Goal:** On-device pill counting using Edge Impulse FOMO object detection

---

## Problem Statement

Count medicine blister pack squares laid flat on a tray, using the OV7675 camera on the Arduino Nano 33 BLE Sense. The count must run entirely on-device (no host PC required for inference). The medicine remains sealed in blister packaging that has been cut into individual squares.

## Architecture

### Dual-Mode Firmware

The existing `nano_33/nano_33.ino` streaming firmware is extended with an inference/counting mode. The two modes share the camera hardware and frame buffer but never run simultaneously.

**Streaming Mode** (existing — used during Phase 1: data collection)

- Captures 160×120 grayscale frames at 5 fps
- Streams raw frames over USB serial using the existing binary protocol (`OVF1` magic, width, height, bpp, format, frame number, size, pixel data)
- Edge Impulse daemon (`edge-impulse-daemon`) reads this stream for live data collection in Edge Impulse Studio

**Counting Mode** (new — used during Phase 2: inference after model deployment)

- Captures a single 160×120 frame, center-crops to 96×96 grayscale
- Feeds the 96×96 buffer to `ei_run_classifier()` from the deployed Edge Impulse Arduino library
- Iterates returned FOMO bounding boxes (centroids)
- Counts boxes where `label == "blister"` and `value >= 0.5`
- Outputs either debug text via `C` or production JSON via `J`

### Mode Transitions

```
Power on → Idle (paused)
    │
    ├── S → Streaming mode (data collection)
    ├── P → Pause streaming
    ├── C → Single capture + count (one-shot)
    ├── J → Single capture + JSON count (production)
    ├── K → Continuous counting loop
    └── X → Stop continuous counting → Idle
```

Streaming and counting are mutually exclusive. Entering counting mode pauses streaming. Entering streaming mode stops continuous counting.

## Serial Command Protocol

The existing firmware uses case-insensitive commands. To add counting without breaking existing functionality, calibrated exposure is remapped from `C`/`c` to lowercase `c` only, freeing uppercase `C` for capture+count.

| Key | Action | Serial Response |
|-----|--------|-----------------|
| `S` / `s` | Start streaming frames | `STREAMING` |
| `P` / `p` | Pause streaming | `PAUSED` |
| `C` | Capture one frame, run inference, output count | `COUNT: <N>` followed by per-detection lines |
| `J` / `j` | Capture one frame, run inference, output production JSON | One JSON object line |
| `K` / `k` | Enter continuous counting (capture + infer loop) | `COUNTING` then `COUNT: <N>` each cycle |
| `X` / `x` | Exit continuous counting | `STOPPED` |
| `F` / `f` | Apply face exposure preset | `FACE_EXPOSURE` |
| `A` / `a` | Apply auto exposure (AGC/AEC/AWB) | `AUTO_EXPOSURE` |
| `c` | Apply calibrated exposure | `CALIBRATED_EXPOSURE` |
| `?` | Print status and command help | Multi-line status block |

## Frame Pipeline for Inference

```
OV7675 sensor (160×120 grayscale, QQVGA)
    │
    ▼
g_frame[] (19,200 bytes)
    │
    ▼
signal_t callback samples the model crop directly from g_frame[]
    │
    ▼
signal_t + ei_run_classifier()
    │
    ▼
ei_impulse_result_t with bounding_boxes[]
    │
    ▼
Count boxes: label == "blister" && value >= 0.5f
    │
    ▼
Serial.println("COUNT: <N>") for debug, or one JSON line for production
```

### Production JSON (`J` command)

The production command returns exactly one JSON object line and no image bytes:

```json
{
  "ok": true,
  "count": 4,
  "boxes": [
    { "label": "blister", "x": 52, "y": 31, "w": 16, "h": 16, "score": 0.91 }
  ],
  "timing_ms": {
    "capture": 420,
    "inference": 860,
    "total": 1280
  }
}
```

Error responses keep the same one-line JSON contract:

```json
{
  "ok": false,
  "error": "INFERENCE_ERROR",
  "code": -1,
  "timing_ms": {
    "capture": 420,
    "inference": 0,
    "total": 420
  }
}
```

## Memory Budget

| Allocation | Size | Notes |
|------------|------|-------|
| `g_frame[]` (streaming buffer) | 19,200 bytes | 160×120×1, always allocated |
| Sampling lookup tables | 288 bytes | Source X and row-offset maps for 96×96 model reads |
| FOMO MobileNetV2 0.35 total inference | ~245 KB | Tensor arena + model temps + weights in SRAM |
| Mbed OS + BLE stack | ~80 KB | System overhead |
| **Sketch global dynamic memory** | ~71 KB | Compile-time global/static use outside runtime heap/stack |

FOMO MobileNetV2 0.35 is designed for small MCU deployments. The firmware keeps one 160×120 frame buffer and does not allocate a second full inference image buffer. During counting mode, streaming is paused.

If memory is too tight at compile time, the fallback is to use FOMO MobileNetV2 0.1 alpha (smaller, faster, slightly less accurate).

## Counting Logic

```cpp
constexpr float kConfidenceThreshold = 0.5f;

int countDetections(const ei_impulse_result_t &result) {
  int count = 0;
  for (uint32_t i = 0; i < result.bounding_boxes_count; ++i) {
    const auto &bb = result.bounding_boxes[i];
    if (bb.value >= kConfidenceThreshold && strcmp(bb.label, "blister") == 0) {
      ++count;
      Serial.print("  det: ");
      Serial.print(bb.label);
      Serial.print(" @ (");
      Serial.print(bb.x);
      Serial.print(",");
      Serial.print(bb.y);
      Serial.print(") conf=");
      Serial.println(bb.value, 2);
    }
  }
  return count;
}
```

### Signal Callback

The Edge Impulse classifier reads pixel data through a `signal_t` callback. The current firmware samples directly from `g_frame[]` using precomputed source-column and row-offset lookup tables, so it avoids a second 96×96 image buffer:

```cpp
int ei_get_frame_data(size_t offset, size_t length, float *out_ptr) {
  // Samples the 96x96 model view from the 160x120 camera frame.
  return 0;
}
```

### One-Shot Count (`C` command)

```cpp
void doSingleCount() {
  Camera.readFrame(g_frame);

  signal_t signal;
  signal.total_length = EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE;
  signal.get_data = &ei_get_frame_data;

  ei_impulse_result_t result;
  EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
  if (err != EI_IMPULSE_OK) {
    Serial.print("INFERENCE_ERROR: ");
    Serial.println(err);
    return;
  }

  int count = countDetections(result);
  Serial.print("COUNT: ");
  Serial.println(count);
}
```

### Production JSON Count (`J` command)

`J` uses the same capture and inference path as `C`, but writes a single JSON object line. It is the command production integrations should call.

### Continuous Count (`K` command)

```cpp
static bool g_counting = false;

// In loop():
if (g_counting) {
  doSingleCount();
  delay(500);  // ~2 counts/sec to avoid overwhelming serial
}
```

## Edge Impulse Workflow

### Phase 1: Setup and Data Collection

1. Install Edge Impulse CLI:
   ```bash
   npm install -g edge-impulse-cli
   ```

2. Create account and project at [edgeimpulse.com](https://edgeimpulse.com)

3. Connect board (firmware in streaming mode):
   ```bash
   edge-impulse-daemon
   ```
   Follow prompts to link to project. Select camera as sensor.

4. In Edge Impulse Studio → **Data Acquisition**:
   - Sensor: Camera
   - Resolution: 96×96 grayscale (Edge Impulse will handle the resize from the raw stream)
   - Capture 80–150 images of blister pack squares on the tray

5. Capture guidelines:
   - Uniform matte background (white or black tray)
   - Consistent diffuse lighting (no shadows)
   - Varying counts per image (1–10 squares)
   - Various positions and orientations
   - Include empty tray images as `background` class
   - Camera perpendicular to tray, fixed distance (~10–15 cm)

### Phase 2: Labeling

1. Edge Impulse Studio → **Labeling Queue**
2. Draw bounding box around each blister pack square
3. Label all as `blister`
4. Confirm auto-propagated labels; fix any errors
5. Every visible square must be labeled — missed labels degrade accuracy

### Phase 3: Impulse Design

| Block | Setting |
|-------|---------|
| Input | Image 96×96 |
| Resize mode | Fit shortest axis |
| Processing Block | Image |
| Color Depth | Grayscale |
| Learning Block | Object Detection (Images) — FOMO |

### Phase 4: Training

| Setting | Value |
|---------|-------|
| Model | FOMO MobileNetV2 0.35 |
| Learning rate | 0.001 |
| Epochs | 60 |
| Batch size | 32 |
| Data augmentation | Enabled (flip, brightness, zoom) |

Target: training accuracy >90%, validation accuracy >85%.

### Phase 5: Testing

- Run all test data through Model Testing tab
- Review F1 score per class
- Check for false positives (background detected as blister)
- Check for missed detections (overlapping squares — FOMO struggles with heavy overlap)

### Phase 6: Deployment

1. Deployment → Arduino Library → Build
2. Download `.zip`
3. Arduino IDE: Sketch → Include Library → Add .ZIP Library
4. The sketch includes the library via `#include <PROJECT_NAME_inferencing.h>` where `PROJECT_NAME` matches the Edge Impulse project name (e.g., `blister_counter_inferencing.h` if the project is named `blister_counter`). The exact name is determined at deployment time.

## Known Limitations

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| FOMO cannot resolve heavy overlap | Undercounting when squares overlap | Arrange squares with gaps on tray |
| 96×96 model input | Small or distant objects may be missed | Fixed camera height, fixed tray, diffuse lighting, tight centered view |
| Grayscale only | Cannot distinguish pills by color | Not needed — counting squares, not pill types |
| No persistent storage | Count lost on power-off | Send count via Serial (or BLE in future) |
| FOMO has no inter-frame memory | Not relevant for static tray counting | One-shot count per command |

## Future Enhancements (Out of Scope)

- BLE notification of count to phone app
- OLED display (I2C) for standalone count readout
- Multi-class detection (different pill types)
- Conveyor/motion counting with centroid tracking
- Confidence threshold tuning via serial command

## File Changes

| File | Change |
|------|--------|
| `nano_33/nano_33.ino` | Add counting mode, inference pipeline, serial commands `C`, `J`, `K`, `X`. Remap calibrated exposure to lowercase `c`. |

No new files are created. The Edge Impulse model library is added via Arduino IDE's library manager after deployment.
