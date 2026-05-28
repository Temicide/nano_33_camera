# H1 Protocol: Precomputed Inference Sampling Map

## Hypothesis

Precomputing the 96x96 model-to-camera sampling map will reduce Edge Impulse callback overhead while adding less than 512 bytes of static RAM.

## Motivation

The firmware keeps one 160x120 grayscale camera frame and feeds the model through `signal_t::get_data`. Before this experiment, each callback pixel recomputed:

- model pixel index to x/y using division and modulo
- source x/y mapping using integer multiply and divide
- grayscale-to-packed-RGB conversion with shifts

This is safe but wasteful on a 64 MHz Cortex-M4.

## Planned Change

- Add `g_sourceXByInferX[96]` as `uint8_t`.
- Add `g_sourceRowOffsetByInferY[96]` as `uint16_t`.
- Fill both tables once during setup.
- Change `ei_get_frame_data()` to iterate row chunks and use lookup offsets.
- Keep the existing camera resolution, grayscale format, resize mode, frame buffer, and model.

## Prediction

Board-side Edge Impulse DSP timing should improve or remain equal. RAM should increase by 288 bytes, which is acceptable relative to the Nano 33 BLE 256 KB SRAM limit and current compile headroom.

## Evaluation

- Compile with `arduino-cli compile --fqbn arduino:mbed_nano:nano33ble ... --warnings all`.
- Compare compile RAM/flash before and after.
- Use the `T` command on hardware to compare `dsp_ms` and `fps_est` against a pre-change build if available.
