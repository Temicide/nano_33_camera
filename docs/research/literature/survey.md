# Literature and Source Survey

This project currently uses local primary sources rather than external papers:

- Installed Edge Impulse model metadata: `~/Documents/Arduino/libraries/pill_counting_inferencing/src/model-parameters/model_metadata.h`
- Installed compiled model source: `~/Documents/Arduino/libraries/pill_counting_inferencing/src/tflite-model/tflite_learn_1011420_3_compiled.cpp`
- Project firmware: `nano_33/nano_33.ino`
- Project design notes: `docs/superpowers/specs/2026-05-27-medicine-counting-fomo-design.md`

Key facts extracted:

- Model input is 96x96 grayscale image data represented through the Edge Impulse image signal path.
- Model input and output are int8.
- The deployed model is FOMO object detection with one `blister` label.
- The compiled tensor arena size is about 154 KB.
- Firmware capture uses QQVGA 160x120 grayscale, one byte per pixel.
