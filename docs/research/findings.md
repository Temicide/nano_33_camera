# Research Findings

## Research Question

How can the Nano 33 BLE reliably perform single-shot blister counting and return one JSON result with high count accuracy and acceptable trigger-to-response latency?

## Current Understanding

The production workflow should be single-shot, not live detection: trigger the camera, capture one stable frame, run the FOMO model once, and return one JSON line. FPS is now a debug metric for `D`/viewer mode rather than the primary optimization target.

The firmware is using the right memory foundation: QQVGA grayscale capture, one 19,200-byte frame buffer, a quantized 96x96 FOMO model, and no second full inference image buffer. The sketch compile after adding production JSON still reports 71,048 bytes of global dynamic memory.

Hardware tests show the single-shot latency target is feasible. Three `J` command trials returned valid one-line JSON with totals of 1,190-1,254 ms, and the board remained responsive to `?` afterward. A low-confidence `blister` box with score 0.00 was initially counted, so the target filter now requires `value >= 0.5` as well as `label == "blister"`.

## Key Results

- H1/H3 run_001 compiled successfully after adding a 96x96 sampling lookup map and continuous-count output reduction.
- Compile memory changed from 70,760 bytes to 71,048 bytes of global dynamic memory, an increase of 288 bytes.
- Flash changed from 193,888 bytes to 194,560 bytes, an increase of 672 bytes.
- Hardware timing is now measurable with the new `T` serial command, which reports capture, total inference, Edge Impulse DSP, neural network, postprocessing, and estimated FPS.
- First hardware profile after upload: `capture_ms=459`, `infer_total_ms=863`, `dsp_ms=14`, `nn_ms=824`, `post_ms=1`, `fps_est=0.76`.
- Five-frame `D` detection stream measured about 0.8 FPS.
- Raising camera init from 5 FPS to 10 FPS compiled with no RAM change but made the firmware non-responsive to `?` and `T`; it was reverted.
- Final restored 5 FPS profile: `capture_ms=397`, `infer_total_ms=863`, `dsp_ms=14`, `nn_ms=824`, `post_ms=1`, `fps_est=0.79`.
- Added the `J` production command, which returns one JSON line with `ok`, `count`, `boxes`, and `timing_ms`, without image bytes.
- `J` compile/upload succeeded with flash at 195,408 bytes and global dynamic memory unchanged at 71,048 bytes.
- Three hardware `J` trials after confidence filtering returned parseable JSON and no image payload: totals were 1,254 ms, 1,190 ms, and 1,190 ms.

## Patterns and Insights

The model callback was doing avoidable per-pixel division and modulo work for each requested model pixel. Precomputing source columns and row offsets keeps the existing camera frame and model preprocessing semantics but moves that work to setup.

Live detection mode still sends the full 160x120 frame after each inference and remains useful for visual debugging. Production should use `J` because it avoids image payload and verbose text.

Effective resolution matters more than FPS for this task. The first improvements should be physical setup changes: fixed camera height, fixed tray position, tray filling the center of the frame, diffuse lighting, and calibrated exposure. Raw camera resolution should not be increased until the fixed 160x120/96x96 path fails validation.

## Lessons and Constraints

- Keep the existing model and OV7675 usage: optimize capture/preprocess/protocol around them.
- Avoid adding another full image buffer. The current firmware removed the older 9,216-byte inference buffer and should keep that RAM headroom.
- Serial text is expensive in continuous loops. Per-box text is useful for one-shot debug but should stay out of continuous count mode.
- Increasing camera FPS alone will not help while capture plus inference exceeds one second per frame.
- Do not use `kCameraFps=10` with the current Arduino_OV767X/Nano 33 setup until it is debugged separately; the responsive setting is 5 FPS.
- Production integrations should use `J`, not `D` or `K`.
- Count filtering must include confidence (`value >= 0.5`); label-only filtering can count zero-score FOMO boxes.
- With the current model, prioritize count accuracy and single-shot latency; only revisit FPS after the JSON path is validated.

## Open Questions

- What fixed camera height and tray position maximize count accuracy with the current 96x96 model?
- Does calibrated exposure improve repeatability over auto exposure for the final physical setup?
- Does the current model reach at least 90% count accuracy across 30 single-shot validation scenes?
- If accuracy fails, is a tighter fixed crop sufficient, or is retraining required?

## Optimization Trajectory

| Run | Change | RAM impact | Compile result | Hardware result |
|---|---:|---:|---|---|
| run_001 | Sampling lookup map, quiet continuous count, timing profile command | +288 bytes | pass | pending |
| run_002 | Board timing and live detection measurement | no code change | pass/uploaded | 0.76-0.8 FPS |
| run_003 | Camera init 10 FPS test | no RAM change | compiled, non-responsive after upload | rejected |
| run_004 | Restore 5 FPS firmware | no code change vs run_002 | pass/uploaded | 0.79 FPS |
| run_005 | Production `J` JSON command and confidence filter | no RAM change | pass/uploaded | 3 JSON trials, 1.19-1.25 s total |
