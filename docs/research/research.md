# Medicine Counting with Arduino Tiny Machine Learning Kit

## Implementation Research Document

> **Sources:** Robocraze TinyML YouTube Playlist · Edge Impulse Documentation · Arduino TinyML Kit Specs · TinyML Vision Counting Case Studies

---

## 1. Hardware Overview

### Arduino Tiny Machine Learning Kit — What's in the Box

| Component                 | Spec / Notes                                                     |
| ------------------------- | ---------------------------------------------------------------- |
| **Microcontroller Board** | Arduino Nano 33 BLE Sense (Lite)                                 |
| **CPU**                   | Nordic nRF52840 · 32-bit ARM Cortex-M4 @ 64 MHz                  |
| **RAM**                   | 256 KB SRAM                                                      |
| **Flash**                 | 1 MB                                                             |
| **Camera**                | OV7675 (VGA, up to 640×480)                                      |
| **Shield**                | Arduino Tiny Machine Learning Shield (mounts both Nano + camera) |
| **Connectivity**          | Bluetooth Low Energy (BLE)                                       |
| **Cable**                 | USB-A to Micro-USB                                               |

### Onboard Sensors on the Nano 33 BLE Sense

The board provides a rich sensor suite beyond the camera — useful for future enhancements:

- IMU: acceleration, rotation, gyroscope (LSM9DS1)
- Microphone (MP34DT05)
- Proximity, gesture, color, light intensity (APDS9960)
- Barometric pressure (LPS22HB)
- _(Note: HTS221 temp/humidity sensor is absent in the Lite variant — does not affect camera projects)_

### OV7675 Camera Specifics

- Max resolution: **640×480 (VGA)**
- Interface: parallel CMOS sensor (controlled via I2C for config, parallel bus for data)
- Relevant library: **`Arduino_OV767x`** (official Arduino library)
- For TinyML inference, images are internally downscaled to **96×96** before being fed into the model
- The camera slots directly into the 2×10 female header on the TML Shield — no additional wiring needed with the kit

---

## 2. Software Stack

### Recommended Toolchain

```
Arduino IDE  ──►  Arduino_OV767x Library  ──►  Edge Impulse CLI
                                                     │
                                                     ▼
                                           Edge Impulse Studio
                                           (cloud: data, training)
                                                     │
                                            Deploy as Arduino Library
                                                     │
                                                     ▼
                                         Arduino Sketch (inference)
```

### Required Libraries & Tools

| Tool / Library                | Purpose                                       | Install Via                       |
| ----------------------------- | --------------------------------------------- | --------------------------------- |
| Arduino IDE (1.8.19+ or 2.x)  | Flashing sketches                             | arduino.cc                        |
| `Arduino Mbed OS Nano Boards` | Board support package                         | Arduino IDE Board Manager         |
| `Arduino_OV767x`              | Camera driver for OV7675                      | Arduino Library Manager           |
| `Harvard_TinyMLx`             | Test sketches for the kit (camera test, etc.) | Arduino Library Manager           |
| `Edge Impulse CLI`            | Connect board to Edge Impulse Studio          | `npm install -g edge-impulse-cli` |
| Node.js (LTS)                 | Dependency for CLI                            | nodejs.org                        |

### Edge Impulse Platform

Edge Impulse is a cloud-based MLOps platform that abstracts the entire TinyML pipeline — data collection, labeling, impulse design, training, and deployment — down to browser-accessible steps. It officially supports the Arduino Nano 33 BLE Sense and the OV7675 camera module.

**Free tier** is sufficient for this project.

---

## 3. ML Strategy for Medicine Counting

### Why FOMO (Faster Objects, More Objects)?

For a pill/medicine counting task on a severely memory-constrained MCU, **FOMO** is the optimal algorithm:

| Property                    | FOMO              | MobileNet SSD | YOLOv5     |
| --------------------------- | ----------------- | ------------- | ---------- |
| RAM usage                   | ~245 KB           | ~MBs          | ~MBs+      |
| Inference speed (Cortex-M4) | Fast (~10–20 fps) | Too slow      | Too slow   |
| Runs on Nano 33 BLE         | ✅ Yes            | ❌ No         | ❌ No      |
| Returns bounding boxes      | Centroids only    | Full boxes    | Full boxes |
| Multi-object counting       | ✅ Yes            | ✅ Yes        | ✅ Yes     |

FOMO works by producing a **grid of centroids** (not full bounding boxes), which is 30× lighter than MobileNet SSD. Each centroid marks the center of a detected object. For counting pills in a static frame (laid on a tray), this is ideal.

### Two Counting Approaches

**Approach A — Static Tray (Recommended for Medicine)**

Place pills on a flat surface and capture a single frame. FOMO detects all pills simultaneously and the count is simply `len(bounding_boxes)`.

```
[Camera above tray]
      |
  OV7675 (96×96 grayscale)
      |
  FOMO inference
      |
  Count centroids → display count
```

This approach is simpler and more reliable for medicine dispensing verification.

**Approach B — Conveyor / Motion Counting**

Pills pass one-by-one under the camera. A centroid-tracking algorithm counts each pill that crosses a threshold line (TOP_Y). This requires the additional post-processing logic from the Edge Impulse object-counting notebook. Not recommended as a first implementation due to complexity.

---

## 4. Full Implementation Workflow

### Phase 1 — Hardware Setup

1. Insert the **Nano 33 BLE Sense** into the TML Shield (align with 2×15 female headers, press firmly).
2. Insert the **OV7675 camera** into the 2×10 female header on the shield (lens facing outward).
3. Connect Micro-USB to your computer.
4. Install board support and libraries in Arduino IDE (see table above).
5. **Test the camera** using the `test_camera` sketch from the `Harvard_TinyMLx` library to confirm the camera is detected and outputting frames before proceeding.

### Phase 2 — Data Collection

**Goal:** Capture ~80–150 images of your target pills on a consistent background.

1. Flash the Edge Impulse firmware to your board:

   ```bash
   edge-impulse-daemon
   ```

   Follow prompts to link to your Edge Impulse project.

2. In **Edge Impulse Studio → Data Acquisition**, select:
   - Device: Arduino Nano 33 BLE Sense
   - Sensor: **Camera**
   - Resolution: 96×96 (grayscale recommended) or 96×96 RGB

3. Capture images with:
   - Pills on a **uniform, matte background** (white or black)
   - Consistent lighting (avoid harsh shadows — use diffuse lighting)
   - Varying number of pills per image (1–10 pills per frame)
   - Various orientations and slight position variations
   - Include some "empty tray" images labeled as `background`

**Recommended dataset split:** 80% training / 20% test

**Minimum viable dataset:** ~50 training images per class. More is better — aim for 100+.

### Phase 3 — Labeling

1. In Edge Impulse Studio → **Labeling Queue**, label each pill in every image by drawing a bounding box around it.
2. Label all pills with a single class: `pill` (or `tablet`, `capsule` — be consistent).
3. Edge Impulse's background tracking algorithm will attempt to auto-carry bounding boxes between similar frames — confirm or adjust them.
4. Ensure every visible pill in every image is labeled — missed labels degrade model accuracy.

### Phase 4 — Impulse Design

Navigate to **Create Impulse**:

| Block            | Setting                                                |
| ---------------- | ------------------------------------------------------ |
| Input            | Image 96×96                                            |
| Resize mode      | Fit shortest axis                                      |
| Processing Block | Image                                                  |
| Color Depth      | **Grayscale** (recommended — faster, uses less memory) |
| Learning Block   | **Object Detection (Images) — FOMO**                   |

Click **Save Impulse**.

Then go to **Image tab → Generate Features**. Review the Feature Explorer to confirm pill features form visually distinct clusters.

### Phase 5 — Training

In **Object Detection tab**:

| Setting           | Recommended Value               |
| ----------------- | ------------------------------- |
| Model             | FOMO MobileNetV2 0.35           |
| Learning rate     | 0.001                           |
| Epochs            | 60                              |
| Batch size        | 32                              |
| Data augmentation | Enable (flip, brightness, zoom) |

Training accuracy target: **>90%**. Validation accuracy: **>85%**.

If accuracy is low:

- Add more diverse images
- Check for unlabeled pills in training data
- Try MobileNetV2 0.1 alpha (lighter, faster to converge on small datasets)

### Phase 6 — Model Testing

Use **Model Testing tab** → Run all test data through the trained model. Review:

- **F1 score** per class
- Any false positives (background detected as pill)
- Any missed pills (check overlapping pills — FOMO struggles with heavy overlap)

**Important caveat:** FOMO cannot reliably distinguish heavily overlapping pills. Keep pills slightly separated on the counting tray for best results.

### Phase 7 — Deployment

1. Go to **Deployment** → Select **Arduino Library** → Click **Build**.
2. Download the generated `.zip` file.
3. In Arduino IDE: **Sketch → Include Library → Add .ZIP Library** → select the zip.
4. Open example: **File → Examples → `<your_project_name>_inferencing` → nano_ble33_sense → nano_ble33_sense_camera**.
5. Modify the example to add counting logic (see code below).
6. Flash to your board.

---

## 5. Arduino Inference Sketch — Medicine Counting

Below is the core inference + counting logic to add to the deployed library's camera example:

```cpp
// After running the classifier, inside the bounding box result loop:

int pill_count = 0;

if (result.bounding_boxes_count > 0) {
    for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
        ei_impulse_result_bounding_box_t bb = result.bounding_boxes[i];
        if (bb.value < 0.5f) continue;  // confidence threshold
        if (strcmp(bb.label, "pill") == 0) {
            pill_count++;
        }
    }
}

ei_printf("Pill count: %d\n", pill_count);

// Optional: BLE notification
// BLE.notify(pill_count);  // if sending to phone
```

For static tray counting, the count is directly `pill_count` after a single inference pass. No frame-to-frame tracking is needed.

---

## 6. Known Limitations & Workarounds

| Limitation                     | Explanation                                                       | Workaround                                                                                        |
| ------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| No FOMO object persistence     | FOMO has no memory between frames                                 | For static tray: count per single frame. For motion: implement centroid tracking (see section 7). |
| Low-res camera (96×96)         | OV7675 downscales to 96×96 for inference                          | Use high-contrast background; keep pills separated                                                |
| Overlapping pills undercounted | FOMO detects centroids; overlapping pills merge into one centroid | Arrange pills in a single layer with small gaps                                                   |
| Grayscale only (recommended)   | RGB is supported but uses 3× memory                               | If pill color matters for type classification, use RGB with caution                               |
| RAM ceiling: 256 KB            | MobileNetV2 0.35 fits; larger models do not                       | Do not use FOMO MobileNetV2 0.5+ — it may not fit                                                 |
| No persistent storage on Nano  | Inference results lost on power-off                               | Send count via BLE to a phone/PC; log via Serial                                                  |

---

## 7. Optional: Centroid Tracking for Motion Counting (Advanced)

If pills are dispensed one-by-one (falling into a bottle, moving on a surface), use the following centroid tracking approach adapted from the Edge Impulse object counting demo:

```cpp
// Global state
static int TOP_Y = 48;          // threshold line (half of 96px image)
static int pill_count_total = 0;
static float prev_cx = -1, prev_cy = -1;

// Inside inference loop:
for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
    auto bb = result.bounding_boxes[i];
    if (bb.value < 0.5f) continue;

    float cx = bb.x + bb.width / 2.0f;
    float cy = bb.y + bb.height / 2.0f;

    // Check if object crossed TOP_Y line downward
    if (prev_cy >= TOP_Y && cy < TOP_Y) {
        pill_count_total++;
        ei_printf("Pill passed line! Total: %d\n", pill_count_total);
    }
    prev_cx = cx;
    prev_cy = cy;
}
```

For a full multi-column tracking implementation, refer to:

- Edge Impulse docs: https://docs.edgeimpulse.com/docs/tutorials/advanced-inferencing/object-counting-using-fomo
- GitHub demo: https://github.com/edgeimpulse/object-counting-demo

---

## 8. Lighting & Physical Setup Recommendations

Good physical setup is as important as the model for pill counting accuracy.

```
         [LED ring / diffuse light source]
                      |
          ┌───────────▼───────────┐
          │   OV7675 Camera       │  ← mounted above tray ~10–15cm
          └───────────────────────┘
                      |
          ┌───────────▼───────────┐
          │  White matte tray     │  ← pills laid flat, single layer
          │  ● ● ● ● ●            │
          │  ● ● ● ●              │
          └───────────────────────┘
```

**Tips:**

- Use a **white or black matte tray** — avoid glossy surfaces (camera glare)
- Use **diffuse, even LED ring lighting** from above to eliminate shadows between pills
- Mount camera **perpendicular to the tray** (straight down), not at an angle
- Maintain a **fixed camera-to-tray distance** (same as training setup)
- Avoid ambient light variation — enclose the setup in a box with only controlled lighting

---

## 9. Robocraze YouTube Playlist — Key Takeaways

The Robocraze playlist (7 videos) covering ML with the Arduino TinyML Kit provides the following progression — relevant topics for the medicine counting project:

1. **Kit setup & Arduino IDE configuration** — installing board packages, connecting to PC, verifying board recognition
2. **Camera initialization** — using `Arduino_OV767x` and the `Harvard_TinyMLx` `test_camera` sketch to confirm OV7675 is working
3. **Edge Impulse connection** — flashing Edge Impulse firmware, running `edge-impulse-daemon`, connecting via CLI
4. **Data acquisition workflow** — capturing images through Edge Impulse Studio's Data Acquisition tab using the live camera feed
5. **Impulse design & feature generation** — creating the ML pipeline, selecting processing and learning blocks
6. **Model training & validation** — running training, interpreting confusion matrices and F1 scores
7. **Deployment & on-device inference** — generating the Arduino library, flashing to board, reading inference output via Serial Monitor

The playlist is the recommended starting reference alongside this document. Work through it in order before adapting the workflow to medicine counting.

---

## 10. Reference Links

| Resource                                        | URL                                                                                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Robocraze TinyML Playlist                       | https://youtube.com/playlist?list=PLUwmiNOPP-7hrRFsplajItGAn5ykUjOgY                                                                 |
| Edge Impulse Arduino Nano 33 BLE Sense Docs     | https://docs.edgeimpulse.com/docs/edge-ai-hardware/mcu/arduino-nano-33-ble-sense                                                     |
| Edge Impulse FOMO Overview                      | https://docs.edgeimpulse.com/docs/edge-impulse-studio/learning-blocks/object-detection/fomo-object-detection-for-constrained-devices |
| Edge Impulse Object Counting Tutorial           | https://docs.edgeimpulse.com/docs/tutorials/advanced-inferencing/object-counting-using-fomo                                          |
| Object Counting Demo (GitHub)                   | https://github.com/edgeimpulse/object-counting-demo                                                                                  |
| Arduino OV767x Library                          | https://github.com/arduino-libraries/Arduino_OV767x                                                                                  |
| Harvard TinyMLx Arduino Library                 | https://github.com/tinyMLx/arduino-library                                                                                           |
| Edge Impulse Firmware for Nano 33 BLE Sense     | https://github.com/edgeimpulse/firmware-arduino-nano-33-ble-sense                                                                    |
| Edge Impulse CLI Setup                          | https://docs.edgeimpulse.com/docs/tools/edge-impulse-cli                                                                             |
| TinyML Vision Counting Case Study (Coders Cafe) | https://medium.com/@coderscafetech/how-tinyml-is-revolutionizing-vision-counting-for-smart-industries-820aae4c5b48                   |

---

## 11. Suggested Implementation Milestones

```
Week 1
  ├── Setup Arduino IDE + board packages + libraries
  ├── Test camera with test_camera sketch
  └── Connect to Edge Impulse, verify camera feed in Studio

Week 2
  ├── Collect 80–120 labeled images of your target pills
  ├── Design Impulse (96×96, Grayscale, FOMO)
  └── Train first model, evaluate accuracy

Week 3
  ├── Deploy model to board as Arduino library
  ├── Run inference sketch, verify pill count via Serial Monitor
  └── Tune: adjust confidence threshold, retrain if needed

Week 4 (optional)
  ├── Add BLE output to send count to phone
  ├── Add display (OLED via I2C) for standalone count readout
  └── Harden physical enclosure (lighting box, fixed mount)
```

---

_Document compiled from: Robocraze TinyML Playlist, Edge Impulse official documentation, Arduino product page, and TinyML vision counting case studies. Last updated: May 2026._
