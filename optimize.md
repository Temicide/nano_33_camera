# Memory Optimization for Arduino Nano 33 BLE Sense — TinyML FOMO Medicine Counter

## Getting a Higher-Resolution Model to Load

> **Problem:** Model cannot be loaded at resolutions above 96×96 on the Nano 33 BLE Sense (256 KB SRAM ceiling)  
> **Goal:** Run FOMO at 160×120 or higher while staying within memory limits

---

## Understanding the Memory Problem

The Nano 33 BLE Sense has **256 KB SRAM total**. That budget must cover everything simultaneously:

```
256 KB total SRAM
├── Mbed OS + BLE stack           ~80 KB  (system, always present)
├── FOMO tensor arena (96×96)    ~120 KB  (inference working memory)
├── Frame buffer (160×120 gray)   ~19 KB  (camera capture)
├── Inference crop buffer (96×96)  ~9 KB  (cropped input)
├── Sketch variables + stack       ~8 KB  (your code)
└── Headroom                      ~20 KB  (safety margin)
                                 ────────
                                 ~256 KB  ← already at ceiling at 96×96
```

Going above 96×96 inference resolution increases the tensor arena proportionally:

- 96×96 → ~120 KB arena (fits)
- 128×128 → ~200 KB arena (too tight)
- 160×160 → ~310 KB arena (does not fit)

Any value over about 180 KB RAM will not work once the model is deployed to the Nano.

The approach is not to increase inference resolution directly, but to **free enough RAM** that a slightly larger model or resolution can coexist with everything else.

---

## Layer 1 — Edge Impulse Side (Do These First)

### 1.1 Switch Model: MobileNetV2 0.35 → 0.1 Alpha

In **Object Detection tab → Choose a different model**:

```
❌ FOMO MobileNetV2 0.35   ~245 KB arena
✅ FOMO MobileNetV2 0.1    ~100 KB arena  ← saves ~145 KB
```

The smallest version of FOMO (96×96 grayscale input, MobileNetV2 0.1 alpha) runs under 100 KB RAM and ~10 fps on a Cortex-M4F at 80 MHz.

This single change frees ~145 KB — the biggest gain of any technique here. Accuracy drops slightly but for a single-class blister counting task the difference is minimal.

### 1.2 Use EON Compiler at Deployment

When deploying as Arduino Library, select **EON Compiler** (or **EON Compiler RAM Optimized**) in the optimization dropdown instead of the default TensorFlow Lite runtime.

Memory is one of the scarcest resources on many microcontrollers, and EON gives developers an option to significantly reduce RAM and ROM on real machine learning models without losing accuracy or increasing latency.

In benchmarking, there were 48 (out of 72) duplicate tensor parameters in the standard FOMO model (MobileNetV2 alpha 0.1), removing them saved 10% of both RAM and flash memory.

EON Compiler RAM Optimized uses layer-by-layer execution to further reduce peak RAM at the cost of slightly slower inference — acceptable for static tray counting.

**Estimated savings: 10–55% RAM reduction depending on model.**

### 1.3 Run EON Tuner (AutoML for Memory)

In Edge Impulse Studio → **EON Tuner** tab:

1. Set target device: **Arduino Nano 33 BLE Sense**
2. Set RAM constraint: `180 KB` maximum
3. Click **Start EON Tuner**

The EON Tuner adjusts performance metrics like inference time and ROM/RAM usage based on the target device selected.

EON Tuner will automatically search across model architectures and input sizes to find the best model that fits within your RAM budget. It may find a configuration that works at 128×128 or a custom size you wouldn't have found manually.

### 1.4 Keep Grayscale (Not RGB)

If you accidentally switched to RGB, switch back. RGB triples the input buffer size:

```
96×96  Grayscale = 9,216 bytes
96×96  RGB       = 27,648 bytes  ← 3× larger, proportionally larger arena
```

Always use **Grayscale** in the Image processing block color depth setting.

---

## Layer 2 — Arduino Sketch Side

These techniques free RAM inside your `.ino` sketch, making more headroom for the model.

### 2.1 Use F() Macro for All Serial Strings

Every string literal in your sketch is copied to RAM at startup by default. The `F()` macro keeps strings in Flash instead.

```cpp
// BAD — string copies to RAM (wastes SRAM)
Serial.println("Inference complete");
Serial.print("COUNT: ");

// GOOD — string stays in Flash (frees SRAM)
Serial.println(F("Inference complete"));
Serial.print(F("COUNT: "));
```

Use the F() macro for constant string literals used in serial output. "Test done. Results:" stored normally uses RAM, but wrapped in F() it will be saved in sketch storage instead, freeing up memory.

**Apply to every `Serial.print()` and `Serial.println()` in your sketch.**  
Typical saving: 50–200 bytes depending on how many strings you have.

### 2.2 Use Smallest Possible Data Types

```cpp
// BAD — wastes memory
int pill_count = 0;        // 4 bytes
long timestamp = 0;        // 8 bytes

// GOOD — minimum size for the job
uint8_t pill_count = 0;    // 1 byte  (max 255 pills — enough)
uint32_t timestamp = 0;    // 4 bytes (sufficient for millis())
```

If you're sure that a value will never exceed 127, you can use a char instead of an int — depending on the platform, this can divide the size of this variable by four.

### 2.3 Avoid String Class Entirely

```cpp
// BAD — String class allocates heap, causes fragmentation
String label = bb.label;
if (label == "blister") { ... }

// GOOD — use strcmp on const char* directly, no heap allocation
if (strcmp(bb.label, "blister") == 0) { ... }
```

The String class always makes a copy of the string passed to the constructor, meaning the string is present twice in RAM. Use const char\* to avoid duplication.

### 2.4 Declare Buffers as Static, Not Global

```cpp
// BAD — global buffers always consume RAM regardless of mode
uint8_t g_frame[19200];
uint8_t g_ei_frame[9216];

// GOOD — static inside function: same persistence, cleaner memory layout
void doCapture() {
  static uint8_t frame[19200];
  static uint8_t ei_frame[9216];
  // ...
}
```

### 2.5 Remove Unused Libraries and Includes

Every `#include` you don't need may pull in code and static buffers behind the scenes.

```cpp
// Remove any of these if not actually used in your sketch:
// #include <Arduino_LSM9DS1.h>   // IMU — not needed for camera counting
// #include <ArduinoBLE.h>        // BLE — remove if not sending count via BLE
// #include <PDM.h>               // Microphone — not needed
```

Check unused libraries — are all the #include libraries actually used? Unused functions — are all the functions actually being called? Unused variables — are all the variables actually being used?

### 2.6 Prefer Stack/Static Over Heap

```cpp
// BAD — heap allocation, causes fragmentation over time
uint8_t* frame = (uint8_t*)malloc(19200);

// GOOD — static allocation, deterministic memory
static uint8_t frame[19200];
```

Allocating and deallocating in the heap causes overhead and fragmentation, so the program can use much less RAM than there is actually on the device.

---

## Layer 3 — Resolution Strategy (The Real Goal)

Since you want **higher capture resolution but need to keep inference at 96×96**, the correct approach is a **capture-wide, infer-small** pipeline:

```
Camera captures at QVGA (320×240)
         ↓
Center-crop to 160×120  ← more scene context than QQVGA crop
         ↓
Downsample to 96×96     ← inference input (tensor arena unchanged)
         ↓
FOMO inference
```

This gives you **more scene context** in the 96×96 inference window without increasing the tensor arena at all. The camera sees more, and the downsample preserves more of the scene.

```cpp
// Step 1: Capture at QVGA instead of QQVGA
Camera.begin(QVGA, GRAYSCALE, 1);  // 320×240 = 76,800 bytes frame buffer

// Step 2: Center-crop 160×120 from 320×240
constexpr uint16_t kCapW  = 320, kCapH  = 240;
constexpr uint16_t kCropW = 160, kCropH = 120;
constexpr uint16_t kCropX = (kCapW - kCropW) / 2;  // = 80
constexpr uint16_t kCropY = (kCapH - kCropH) / 2;  // = 60

static uint8_t g_frame[kCapW * kCapH];        // 76,800 bytes
static uint8_t g_ei_frame[kCropW * kCropH];   // 19,200 bytes (160×120)

void cropFrame() {
  for (uint16_t y = 0; y < kCropH; ++y) {
    memcpy(
      &g_ei_frame[y * kCropW],
      &g_frame[(y + kCropY) * kCapW + kCropX],
      kCropW
    );
  }
}

// Step 3: Edge Impulse signal reads from g_ei_frame (160×120)
// The library's internal resize handles 160×120 → 96×96 before inference
```

**Tradeoff:** QVGA frame buffer is 76,800 bytes vs QQVGA's 19,200 bytes — costs 57 KB more RAM. Only viable after freeing RAM from Layer 1 (model + EON Compiler).

---

## Memory Budget After All Optimizations

| Component                     | Before (0.35, no EON) | After (0.1 + EON Compiler) |
| ----------------------------- | --------------------- | -------------------------- |
| FOMO tensor arena             | ~245 KB               | ~90 KB                     |
| Frame buffer (QQVGA)          | 19 KB                 | 19 KB                      |
| Frame buffer (QVGA upgrade)   | —                     | 76 KB                      |
| Inference buffer (96×96)      | 9 KB                  | 9 KB                       |
| Mbed OS + BLE stack           | 80 KB                 | 80 KB                      |
| Sketch + stack                | 8 KB                  | ~6 KB                      |
| **Total (QQVGA path)**        | **~361 KB ❌**        | **~204 KB ✅**             |
| **Total (QVGA upgrade path)** | —                     | **~261 KB ⚠️ tight**       |

---

## Recommended Action Order

```
Step 1  Switch to FOMO MobileNetV2 0.1 alpha in Edge Impulse training
        → Biggest single gain (~145 KB freed)

Step 2  Use EON Compiler (RAM Optimized) at deployment
        → Additional 10–55% reduction

Step 3  Apply F() macro to all Serial strings in sketch
        → Easy 50–200 bytes freed

Step 4  Remove unused #include libraries from sketch
        → Variable savings

Step 5  Test: does model load at 96×96 inference + QQVGA capture?
        → Should work comfortably now

Step 6  If RAM headroom > 60 KB, upgrade capture to QVGA (320×240)
        → Wider field of view, same 96×96 inference, no arena change
        → Monitor total RAM — stay under 220 KB

Step 7  Run EON Tuner to find if 128×128 inference fits within budget
        → May unlock slightly better detection at no extra code cost
```

---

## Quick Reference Table

| Technique                            | Where                   | RAM Saved             | Effort |
| ------------------------------------ | ----------------------- | --------------------- | ------ |
| Switch to MobileNetV2 0.1 alpha      | Edge Impulse            | ~145 KB               | Low    |
| EON Compiler RAM Optimized           | Edge Impulse deployment | 10–55%                | Low    |
| EON Tuner AutoML                     | Edge Impulse            | Variable              | Low    |
| F() macro on all Serial strings      | Arduino sketch          | 50–200 B              | Low    |
| Remove unused #includes              | Arduino sketch          | Variable              | Low    |
| uint8_t instead of int for counters  | Arduino sketch          | Bytes per var         | Low    |
| Avoid String class, use const char\* | Arduino sketch          | Hundreds of B         | Medium |
| Static allocation over malloc/heap   | Arduino sketch          | Reduces fragmentation | Medium |
| QVGA capture + center-crop strategy  | Arduino sketch          | -57 KB (costs RAM)    | Medium |

---

## Key Rule to Never Forget

The RAM reported in Edge Impulse training is for inferencing only (tensor arena). It does not include camera buffers, your sketch variables, or the OS stack. Always budget:

```
Safe limit = 256 KB - 80 KB (OS) - 20 KB (sketch+stack) = 156 KB for model + buffers
```

Keep model arena + frame buffers under **156 KB** for reliable operation.

---

_Sources: Arduino Memory Optimization Guide (support.arduino.cc), ArduinoJson Memory Tips (arduinojson.org), Edge Impulse FOMO Documentation, EON Compiler announcements, Hackster.io TinyML Nano 33 BLE project._
