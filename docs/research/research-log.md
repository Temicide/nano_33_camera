# Research Log

Chronological record of research decisions and actions. Append-only.

| # | Date | Type | Summary |
|---|------|------|---------|
| 1 | 2026-05-28 | bootstrap | Inspected Nano 33 BLE firmware, Edge Impulse model metadata, host detection viewers, and compile output. Confirmed current baseline keeps QQVGA grayscale, one 19,200-byte camera buffer, a 96x96 int8 FOMO model, and no second inference image buffer. |
| 2 | 2026-05-28 | inner-loop | H1/H3 run_001: optimized the Edge Impulse signal callback with a 288-byte sampling lookup map, added `T` timing profile command, and made continuous counting print counts without per-box detail. Compile passed; RAM changed from 70,760 to 71,048 bytes and flash from 193,888 to 194,560 bytes. |
| 3 | 2026-05-28 | outer-loop | Synthesis: the next largest FPS ceiling is likely serial payload in detection stream, because every `D` frame sends the full 160x120 grayscale image after inference. Recommended next tests are board-side `T` timing and a protocol experiment that streams the 96x96 model crop or decimates preview frames. |
| 4 | 2026-05-28 | report | Generated `to_human/fps-optimization-report.html` summarizing implemented changes, memory impact, and next optimization candidates. |
| 5 | 2026-05-28 | inner-loop | H1/H2 run_002: uploaded firmware after one transient SAM-BA write failure and retry. `T` profile reported capture_ms=459, infer_total_ms=863, dsp_ms=14, nn_ms=824, post_ms=1, fps_est=0.76. Five-frame detection stream measured about 0.8 FPS. |
| 6 | 2026-05-28 | outer-loop | Revised bottleneck diagnosis: with the current deployed model, NN inference dominates. Serial full-frame transfer is not yet the primary ceiling; optimize model/runtime first, then revisit detection payload once inference is faster. |
| 7 | 2026-05-28 | inner-loop | H4 run_003: changed camera init from 5 FPS to 10 FPS. Compile RAM/flash were unchanged, but after upload the firmware did not respond to `?` or `T`, so the setting was rejected as unsafe for this board/library combination. |
| 8 | 2026-05-28 | inner-loop | H4 run_004: restored camera init to 5 FPS and uploaded via direct `arduino-cli upload -p /dev/cu.usbmodem114301`. Final `T` profile reported capture_ms=397, infer_total_ms=863, dsp_ms=14, nn_ms=824, post_ms=1, fps_est=0.79. |
| 9 | 2026-05-28 | outer-loop | Pivoted research direction from live FPS optimization to production single-shot JSON counting. Primary metric is now count accuracy on fixed validation scenes; secondary metric is trigger-to-JSON latency. |
| 10 | 2026-05-28 | inner-loop | H5/H6 run_005: added `J` production command for one-line JSON with count, boxes, and timing. Initial hardware test exposed a zero-score `blister` box, so target filtering now requires `value >= 0.5` plus label match. Compile passed with flash=195408 bytes and RAM=71048 bytes. Upload succeeded after one transient SAM-BA retry. Three `J` trials returned valid JSON with totals 1254 ms, 1190 ms, and 1190 ms; `?` remained responsive. |
