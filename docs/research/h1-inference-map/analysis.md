# H1 Analysis

## Implementation

Implemented in `nano_33/nano_33.ino`.

- Added 96 source-column entries and 96 source-row-offset entries.
- Reworked `ei_get_frame_data()` to process row chunks and avoid per-pixel coordinate divisions.
- Kept grayscale camera capture and packed RGB values for Edge Impulse image preprocessing compatibility.
- Added the `T` profile command for future hardware timing.
- Suppressed verbose per-box serial output in continuous count mode.

## Compile Result

Command:

```bash
arduino-cli compile --fqbn arduino:mbed_nano:nano33ble /Users/temicide/Documents/nano_33/nano_33 --warnings all
```

Result:

- Program storage: 194,560 bytes of 983,040 bytes.
- Global dynamic memory: 71,048 bytes of 262,144 bytes.
- Previous compile before this patch: 193,888 bytes flash and 70,760 bytes global dynamic memory.
- Delta: +672 bytes flash, +288 bytes global dynamic memory.

Warnings are from the installed Edge Impulse/Arduino libraries and an existing unused SCCB register read helper; the sketch compiled.

## Interpretation

The RAM tradeoff matches the protocol prediction exactly. The change is safe for memory pressure because it does not add a second image buffer and does not alter tensor arena size.

Hardware FPS impact remains pending until the board runs `T` and detection stream tests.

## Hardware Result

After upload, command `T` reported:

```text
PROFILE count=1 capture_ms=459 infer_total_ms=863 dsp_ms=14 nn_ms=824 post_ms=1 fps_est=0.76
```

The five-frame live detection viewer reported:

```text
fps=1.0 count=1
fps=0.8 count=1
fps=0.8 count=1
fps=0.8 count=1
Processed 5 detection frames
```

This shifts the bottleneck diagnosis. The precomputed map is still a low-risk cleanup, but the current deployed model is dominated by NN inference time. DSP callback work is only about 14 ms after the patch, and serial preview is not the main limiter at the current 0.8 FPS level.

A follow-up `kCameraFps=10` test compiled with no RAM change but made the firmware non-responsive after upload, so it was reverted. The restored 5 FPS firmware responded and reported:

```text
PROFILE count=1 capture_ms=397 infer_total_ms=863 dsp_ms=14 nn_ms=824 post_ms=1 fps_est=0.79
```
