#include <Arduino.h>
#include <Arduino_OV767X.h>
#include <Wire.h>
#include <string.h>
#include <pill_counting_inferencing.h>

#if defined(ARDUINO_ARCH_MBED)
#include <mbed.h>
#include <platform/mbed_stats.h>
#endif

namespace {

constexpr unsigned long kSerialBaud = 921600;
constexpr uint8_t kShieldButtonPin = 13;
constexpr int kCameraResolution = QQVGA;
constexpr uint8_t kCameraFps = 5;
constexpr uint16_t kFrameWidth = 160;
constexpr uint16_t kFrameHeight = 120;
constexpr uint8_t kBytesPerPixel = 1;
constexpr uint8_t kFormatGrayscale = 0;
constexpr uint32_t kFrameBytes =
    static_cast<uint32_t>(kFrameWidth) * kFrameHeight * kBytesPerPixel;
static_assert(kFrameWidth <= 65535,
              "Frame width must fit the binary stream header");
static_assert(kFrameHeight <= 65535,
              "Frame height must fit the binary stream header");
static_assert(kFrameBytes <= 19200,
              "Production capture must stay at or below 160x120 grayscale");
constexpr uint8_t kFrameMagic[] = {'O', 'V', 'F', '1'};
constexpr uint8_t kDetectionMagic[] = {'O', 'V', 'D', '1'};
constexpr uint16_t kInferWidth = EI_CLASSIFIER_INPUT_WIDTH;
constexpr uint16_t kInferHeight = EI_CLASSIFIER_INPUT_HEIGHT;
constexpr uint32_t kInferPixels =
    static_cast<uint32_t>(kInferWidth) * kInferHeight;
static_assert(kInferPixels == EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE,
              "Edge Impulse DSP input must match a single grayscale frame");
static_assert(kFrameWidth >= kInferWidth && kFrameHeight >= kInferHeight,
              "Camera frame must be at least as large as model input");
static_assert(kFrameWidth <= 256,
              "Source X lookup table stores camera columns as uint8_t");
static_assert((static_cast<uint32_t>(kFrameHeight - 1) * kFrameWidth) <= 65535,
              "Source row-offset lookup table stores byte offsets as uint16_t");
#if EI_CLASSIFIER_RESIZE_MODE != EI_CLASSIFIER_RESIZE_FIT_SHORTEST
#error "Update ei_get_frame_data() to match the Edge Impulse resize mode"
#endif
// Match Edge Impulse's EI_CLASSIFIER_RESIZE_FIT_SHORTEST preprocessing:
// center-crop the camera image to the model aspect ratio, then downsample.
constexpr uint32_t kFrameAspect = static_cast<uint32_t>(kFrameWidth) * kInferHeight;
constexpr uint32_t kInferAspect = static_cast<uint32_t>(kInferWidth) * kFrameHeight;
constexpr bool kCropFrameWidth = kFrameAspect > kInferAspect;
constexpr uint16_t kModelSourceWidth =
    kCropFrameWidth ? static_cast<uint16_t>(
                          (static_cast<uint32_t>(kFrameHeight) * kInferWidth) /
                          kInferHeight)
                    : kFrameWidth;
constexpr uint16_t kModelSourceHeight =
    kCropFrameWidth ? kFrameHeight
                    : static_cast<uint16_t>(
                          (static_cast<uint32_t>(kFrameWidth) * kInferHeight) /
                          kInferWidth);
constexpr uint16_t kModelSourceX = (kFrameWidth - kModelSourceWidth) / 2;
constexpr uint16_t kModelSourceY = (kFrameHeight - kModelSourceHeight) / 2;
constexpr uint32_t kCountIntervalMs = 500;
constexpr uint32_t kWatchdogTimeoutMs = 8000;
constexpr float kConfidenceThreshold = 0.5f;
constexpr int kFaceExposure = 900;
constexpr int kFaceGain = 145;
constexpr int kFaceBrightness = 128;
constexpr int kFaceContrast = 72;
constexpr int kFaceSaturation = 90;
// Sensor-default SDE values used when re-entering auto mode. These match the
// OV7675 power-on defaults so the on-sensor AGC/AEC/AWB loop runs unhindered.
constexpr int kAutoBrightness = 0;
constexpr int kAutoContrast = 64;
constexpr int kAutoSaturation = 128;
// Number of frames to warm up the AGC/AEC/AWB loop after entering auto mode
// before client-visible streaming should be considered stable.
constexpr uint8_t kAutoWarmupFrames = 30;

// ---------- calibrated exposure preset (SCCB register-level) ----------------
// Disables AEC, AGC, AWB for frame-to-frame consistency under fixed lighting.
// All values are tunable — adjust to your lighting and subject.
constexpr int kCalExposure = 300;
constexpr int kCalGain = 100;
constexpr int kCalBrightness = 128;
constexpr int kCalContrast = 72;
constexpr int kCalSaturation = 110;
constexpr uint8_t kCalBlueGain = 0x5C;
constexpr uint8_t kCalRedGain = 0x5C;

// OV7675 SCCB register addresses (subset from sensor datasheet)
constexpr uint8_t kCamRegBlue = 0x01;
constexpr uint8_t kCamRegRed = 0x02;
constexpr uint8_t kCamRegCOM3 = 0x0C;
constexpr uint8_t kCamRegCLKRC = 0x11;
constexpr uint8_t kCamRegCOM7 = 0x12;
constexpr uint8_t kCamRegCOM8 = 0x13;
constexpr uint8_t kCamRegCOM9 = 0x14;
constexpr uint8_t kCamRegCOM14 = 0x3E;
constexpr uint8_t kCamRegBanding50 = 0x22;
constexpr uint8_t kCamRegBandingStep = 0x23;
constexpr uint8_t kCamRegDBLV = 0x6B;

// COM8 bit-fields
constexpr uint8_t kCOM8_AEC = 0x01;
constexpr uint8_t kCOM8_AWB = 0x02;
constexpr uint8_t kCOM8_AGC = 0x04;
constexpr uint8_t kCOM8_BFILT = 0x20;
constexpr uint8_t kCOM8_AECSTEP = 0x40;
constexpr uint8_t kCOM8_FASTAEC = 0x80;

// 7-bit I²C address for OV7675 (0x42 >> 1)
constexpr uint8_t kOV7675I2CAddr = 0x21;

// Write one byte to an OV7675 SCCB register via Wire
void wrOV7675Reg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(kOV7675I2CAddr);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

// Read one byte from an OV7675 SCCB register via Wire.
// Returns 0 on success; non-zero means the read failed.
int rdOV7675Reg(uint8_t reg, uint8_t &value) {
  Wire.beginTransmission(kOV7675I2CAddr);
  Wire.write(reg);
  if (Wire.endTransmission() != 0) {
    return -1;
  }
  if (Wire.requestFrom(kOV7675I2CAddr, static_cast<uint8_t>(1)) != 1) {
    return -1;
  }
  value = static_cast<uint8_t>(Wire.read());
  return 0;
}

static uint8_t g_frame[kFrameBytes];
static uint8_t g_sourceXByInferX[kInferWidth];
static uint16_t g_sourceRowOffsetByInferY[kInferHeight];
static bool g_streaming = false;
static bool g_detecting = false;
static uint32_t g_frameNumber = 0;
static bool g_counting = false;

#if defined(DEVICE_WATCHDOG)
mbed::Watchdog *g_watchdog = nullptr;
#endif

void kickWatchdog() {
#if defined(DEVICE_WATCHDOG)
  if (g_watchdog != nullptr) {
    g_watchdog->kick();
  }
#endif
}

void startWatchdog() {
#if defined(DEVICE_WATCHDOG)
  g_watchdog = &mbed::Watchdog::get_instance();
  g_watchdog->start(kWatchdogTimeoutMs);
  kickWatchdog();
#endif
}

void initializeShieldPins() {
  pinMode(kShieldButtonPin, OUTPUT);
  digitalWrite(kShieldButtonPin, HIGH);
}

void writeU16(uint16_t value) {
  uint8_t bytes[2] = {
      static_cast<uint8_t>(value & 0xFF),
      static_cast<uint8_t>((value >> 8) & 0xFF),
  };
  Serial.write(bytes, sizeof(bytes));
}

void writeU32(uint32_t value) {
  uint8_t bytes[4] = {
      static_cast<uint8_t>(value & 0xFF),
      static_cast<uint8_t>((value >> 8) & 0xFF),
      static_cast<uint8_t>((value >> 16) & 0xFF),
      static_cast<uint8_t>((value >> 24) & 0xFF),
  };
  Serial.write(bytes, sizeof(bytes));
}

void writeFrameHeader() {
  Serial.write(kFrameMagic, sizeof(kFrameMagic));
  writeU16(kFrameWidth);
  writeU16(kFrameHeight);
  Serial.write(kBytesPerPixel);
  Serial.write(kFormatGrayscale);
  writeU32(g_frameNumber);
  writeU32(kFrameBytes);
}

void writeDetectionHeader(uint16_t detectionCount) {
  Serial.write(kDetectionMagic, sizeof(kDetectionMagic));
  writeU16(kFrameWidth);
  writeU16(kFrameHeight);
  Serial.write(kBytesPerPixel);
  Serial.write(kFormatGrayscale);
  writeU32(g_frameNumber);
  writeU32(kFrameBytes);
  writeU16(detectionCount);
}

void printReady() {
  Serial.println();
  Serial.println("NANO33_OV7675_READY");
  Serial.print("width=");
  Serial.println(kFrameWidth);
  Serial.print("height=");
  Serial.println(kFrameHeight);
  Serial.print("bytes_per_frame=");
  Serial.println(kFrameBytes);
  Serial.println(
      "commands: S=start, P=pause, C=count, J=json count, K=continuous count, "
      "D=detect stream, X=stop count/detect, F=face exp, A=auto exp, "
      "c=cal exp, T=profile, M=memory, ?=status");
}

void printMemoryStatus() {
  Serial.print("MEM frame_bytes=");
  Serial.print(kFrameBytes);
  Serial.print(" capture=");
  Serial.print(kFrameWidth);
  Serial.print("x");
  Serial.print(kFrameHeight);
  Serial.print(" ei_input=");
  Serial.print(EI_CLASSIFIER_INPUT_WIDTH);
  Serial.print("x");
  Serial.print(EI_CLASSIFIER_INPUT_HEIGHT);
  Serial.print(" ei_dsp_frame=");
  Serial.print(EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE);
  Serial.print(" ei_engine=");
  Serial.print(EI_CLASSIFIER_INFERENCING_ENGINE);
  Serial.print(" ei_deploy=");
  Serial.print(EI_CLASSIFIER_PROJECT_DEPLOY_VERSION);
  Serial.print(" ei_input_type=");
  Serial.print(EI_CLASSIFIER_TFLITE_INPUT_DATATYPE);
  Serial.print(" ei_largest_arena=");
  Serial.print(EI_CLASSIFIER_TFLITE_LARGEST_ARENA_SIZE);
#if defined(EI_CLASSIFIER_ALLOCATION_STATIC)
  Serial.print(" ei_alloc=static");
#else
  Serial.print(" ei_alloc=heap");
#endif
#if defined(ARDUINO_ARCH_MBED)
  mbed_stats_heap_t heapStats;
  mbed_stats_heap_get(&heapStats);
  Serial.print(" heap_current=");
  Serial.print(heapStats.current_size);
  Serial.print(" heap_max=");
  Serial.print(heapStats.max_size);
  Serial.print(" heap_reserved=");
  Serial.print(heapStats.reserved_size);
  Serial.print(" heap_allocs=");
  Serial.print(heapStats.alloc_cnt);
  Serial.print(" heap_failures=");
  Serial.print(heapStats.alloc_fail_cnt);
#endif
  Serial.println();
}

// Manual face-tuned preset. Locks AGC/AEC and (on this sensor) effectively
// freezes AWB at its current state, so colors won't adapt to lighting.
void applyFaceExposure() {
  Camera.setBrightness(kFaceBrightness);
  Camera.setContrast(kFaceContrast);
  Camera.setSaturation(kFaceSaturation);
  Camera.setGain(kFaceGain);
  Camera.setExposure(kFaceExposure);
  Serial.println("FACE_EXPOSURE");
}

// Restores SDE registers to neutral and re-enables on-sensor AGC/AEC. AWB
// runs as long as we don't subsequently call setGain()/setExposure().
void applyAutoExposure() {
  Camera.setBrightness(kAutoBrightness);
  Camera.setContrast(kAutoContrast);
  Camera.setSaturation(kAutoSaturation);
  Camera.autoGain();
  Camera.autoExposure();
  Serial.println("AUTO_EXPOSURE");
}

void applyCalibratedExposure() {
  Camera.setExposure(kCalExposure);
  Camera.setGain(kCalGain);
  Camera.setBrightness(kCalBrightness);
  Camera.setContrast(kCalContrast);
  Camera.setSaturation(kCalSaturation);

  // ---- SCCB register-level fine-tuning ----

  // Disable AWB (AEC and AGC already disabled by setExposure/setGain above).
  // No read-modify-write — known value after setExposure + setGain clears AEC/AGC.
  wrOV7675Reg(kCamRegCOM8, kCOM8_FASTAEC | kCOM8_AECSTEP);

  // Manual white-balance channel gains
  wrOV7675Reg(kCamRegBlue, kCalBlueGain);
  wrOV7675Reg(kCamRegRed, kCalRedGain);

  delay(50);
  Serial.println("CALIBRATED_EXPOSURE");
}

void warmupCamera(uint8_t frames) {
  for (uint8_t i = 0; i < frames; ++i) {
    Camera.readFrame(g_frame);
    kickWatchdog();
  }
}

void initializeInferenceMap() {
  for (uint16_t x = 0; x < kInferWidth; ++x) {
    g_sourceXByInferX[x] = static_cast<uint8_t>(
        kModelSourceX +
        ((static_cast<uint32_t>(x) * kModelSourceWidth) + (kInferWidth / 2)) /
            kInferWidth);
  }

  for (uint16_t y = 0; y < kInferHeight; ++y) {
    const uint16_t srcY =
        kModelSourceY +
        ((static_cast<uint32_t>(y) * kModelSourceHeight) + (kInferHeight / 2)) /
            kInferHeight;
    g_sourceRowOffsetByInferY[y] =
        static_cast<uint16_t>(static_cast<uint32_t>(srcY) * kFrameWidth);
  }
}

int ei_get_frame_data(size_t offset, size_t length, float *out_ptr) {
  if (offset + length > kInferPixels) {
    return -1;
  }

  uint16_t y = static_cast<uint16_t>(offset / kInferWidth);
  uint16_t x = static_cast<uint16_t>(
      offset - (static_cast<size_t>(y) * kInferWidth));
  size_t outIndex = 0;
  size_t remaining = length;

  while (remaining > 0) {
    uint16_t rowRun = kInferWidth - x;
    if (rowRun > remaining) {
      rowRun = static_cast<uint16_t>(remaining);
    }

    const uint16_t rowOffset = g_sourceRowOffsetByInferY[y];
    for (uint16_t i = 0; i < rowRun; ++i) {
      const uint8_t gray =
          g_frame[static_cast<size_t>(rowOffset) + g_sourceXByInferX[x + i]];
      out_ptr[outIndex++] =
          static_cast<float>(static_cast<uint32_t>(gray) * 0x00010101UL);
    }

    remaining -= rowRun;
    x = 0;
    ++y;
  }
  return 0;
}

bool isTargetDetection(const ei_impulse_result_bounding_box_t &bb) {
  return bb.value >= kConfidenceThreshold && strcmp(bb.label, "blister") == 0;
}

int countDetections(const ei_impulse_result_t &result, bool verbose) {
  int count = 0;
  for (uint32_t i = 0; i < result.bounding_boxes_count; ++i) {
    const auto &bb = result.bounding_boxes[i];
    if (isTargetDetection(bb)) {
      ++count;
      if (verbose) {
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
  }
  return count;
}

uint16_t countTargetDetections(const ei_impulse_result_t &result) {
  uint16_t count = 0;
  for (uint32_t i = 0; i < result.bounding_boxes_count; ++i) {
    if (isTargetDetection(result.bounding_boxes[i])) {
      ++count;
    }
  }
  return count;
}

uint16_t clampU16(uint32_t value, uint16_t maxValue) {
  return static_cast<uint16_t>(value > maxValue ? maxValue : value);
}

struct FrameBox {
  uint16_t x;
  uint16_t y;
  uint16_t w;
  uint16_t h;
};

FrameBox mapDetectionBoxToFrame(const ei_impulse_result_bounding_box_t &bb) {
  FrameBox box;
  box.x =
      clampU16(kModelSourceX +
                   (static_cast<uint32_t>(bb.x) * kModelSourceWidth) / kInferWidth,
               kFrameWidth);
  box.y =
      clampU16(kModelSourceY +
                   (static_cast<uint32_t>(bb.y) * kModelSourceHeight) / kInferHeight,
               kFrameHeight);
  box.w = clampU16(
      ((static_cast<uint32_t>(bb.width) * kModelSourceWidth) + kInferWidth - 1) /
          kInferWidth,
      kFrameWidth - box.x);
  box.h = clampU16(
      ((static_cast<uint32_t>(bb.height) * kModelSourceHeight) + kInferHeight - 1) /
          kInferHeight,
      kFrameHeight - box.y);
  return box;
}

void writeDetectionBox(const ei_impulse_result_bounding_box_t &bb) {
  const FrameBox box = mapDetectionBoxToFrame(bb);
  const uint16_t confidence =
      clampU16(static_cast<uint32_t>(bb.value * 10000.0f), 10000);

  writeU16(box.x);
  writeU16(box.y);
  writeU16(box.w);
  writeU16(box.h);
  writeU16(confidence);
}

void printJsonString(const char *value) {
  Serial.write('"');
  while (*value != '\0') {
    const char c = *value++;
    switch (c) {
    case '"':
      Serial.print("\\\"");
      break;
    case '\\':
      Serial.print("\\\\");
      break;
    case '\n':
      Serial.print("\\n");
      break;
    case '\r':
      Serial.print("\\r");
      break;
    case '\t':
      Serial.print("\\t");
      break;
    default:
      Serial.write(c >= 0x20 ? c : '?');
      break;
    }
  }
  Serial.write('"');
}

void printJsonTiming(uint32_t captureMs, uint32_t inferenceMs) {
  Serial.print("\"timing_ms\":{\"capture\":");
  Serial.print(captureMs);
  Serial.print(",\"inference\":");
  Serial.print(inferenceMs);
  Serial.print(",\"total\":");
  Serial.print(captureMs + inferenceMs);
  Serial.print("}");
}

void printJsonError(const char *error, int code, uint32_t captureMs,
                    uint32_t inferenceMs) {
  Serial.print("{\"ok\":false,\"error\":");
  printJsonString(error);
  Serial.print(",\"code\":");
  Serial.print(code);
  Serial.print(",");
  printJsonTiming(captureMs, inferenceMs);
  Serial.println("}");
}

EI_IMPULSE_ERROR runInference(ei_impulse_result_t &result) {
  signal_t signal;
  signal.total_length = EI_CLASSIFIER_DSP_INPUT_FRAME_SIZE;
  signal.get_data = &ei_get_frame_data;

  return run_classifier(&signal, &result, false);
}

void printInferenceError(EI_IMPULSE_ERROR err) {
  Serial.print("INFERENCE_ERROR: ");
  Serial.println(err);
}

void doSingleCount(bool verboseDetections) {
  Camera.readFrame(g_frame);

  ei_impulse_result_t result;
  EI_IMPULSE_ERROR err = runInference(result);
  if (err != EI_IMPULSE_OK) {
    printInferenceError(err);
    return;
  }

  int count = countDetections(result, verboseDetections);
  Serial.print("COUNT: ");
  Serial.println(count);
}

void doJsonCount() {
  const uint32_t captureStartMs = millis();
  Camera.readFrame(g_frame);
  const uint32_t captureMs = millis() - captureStartMs;

  ei_impulse_result_t result;
  const uint32_t inferStartMs = millis();
  EI_IMPULSE_ERROR err = runInference(result);
  const uint32_t inferMs = millis() - inferStartMs;
  if (err != EI_IMPULSE_OK) {
    printJsonError("INFERENCE_ERROR", static_cast<int>(err), captureMs, inferMs);
    return;
  }

  const uint16_t count = countTargetDetections(result);
  Serial.print("{\"ok\":true,\"count\":");
  Serial.print(count);
  Serial.print(",\"boxes\":[");

  bool first = true;
  for (uint32_t i = 0; i < result.bounding_boxes_count; ++i) {
    const auto &bb = result.bounding_boxes[i];
    if (!isTargetDetection(bb)) {
      continue;
    }

    const FrameBox box = mapDetectionBoxToFrame(bb);
    if (!first) {
      Serial.print(",");
    }
    first = false;

    Serial.print("{\"label\":");
    printJsonString(bb.label);
    Serial.print(",\"x\":");
    Serial.print(box.x);
    Serial.print(",\"y\":");
    Serial.print(box.y);
    Serial.print(",\"w\":");
    Serial.print(box.w);
    Serial.print(",\"h\":");
    Serial.print(box.h);
    Serial.print(",\"score\":");
    Serial.print(bb.value, 2);
    Serial.print("}");
  }

  Serial.print("],");
  printJsonTiming(captureMs, inferMs);
  Serial.println("}");
}

void doTimedCount() {
  const uint32_t captureStartMs = millis();
  Camera.readFrame(g_frame);
  const uint32_t captureMs = millis() - captureStartMs;

  ei_impulse_result_t result;
  const uint32_t inferStartMs = millis();
  EI_IMPULSE_ERROR err = runInference(result);
  const uint32_t inferMs = millis() - inferStartMs;
  if (err != EI_IMPULSE_OK) {
    printInferenceError(err);
    return;
  }

  const uint16_t count = countTargetDetections(result);
  const uint32_t totalMs = captureMs + inferMs;
  Serial.print("PROFILE count=");
  Serial.print(count);
  Serial.print(" capture_ms=");
  Serial.print(captureMs);
  Serial.print(" infer_total_ms=");
  Serial.print(inferMs);
  Serial.print(" dsp_ms=");
  Serial.print(result.timing.dsp);
  Serial.print(" nn_ms=");
  Serial.print(result.timing.classification);
  Serial.print(" post_ms=");
  Serial.print(result.timing.postprocessing);
  Serial.print(" fps_est=");
  Serial.println(totalMs > 0 ? (1000.0f / static_cast<float>(totalMs)) : 0.0f, 2);
}

void doDetectionFrame() {
  Camera.readFrame(g_frame);

  ei_impulse_result_t result;
  const EI_IMPULSE_ERROR err = runInference(result);
  const uint16_t detectionCount =
      err == EI_IMPULSE_OK ? countTargetDetections(result) : 0;

  if (err != EI_IMPULSE_OK) {
    printInferenceError(err);
  }

  writeDetectionHeader(detectionCount);
  if (err == EI_IMPULSE_OK) {
    for (uint32_t i = 0; i < result.bounding_boxes_count; ++i) {
      const auto &bb = result.bounding_boxes[i];
      if (isTargetDetection(bb)) {
        writeDetectionBox(bb);
      }
    }
  }
  Serial.write(g_frame, kFrameBytes);
  Serial.flush();
  ++g_frameNumber;
}

void fatalBlink(const char *message) {
  Serial.println(message);
  pinMode(LED_BUILTIN, OUTPUT);

  for (;;) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(150);
    digitalWrite(LED_BUILTIN, LOW);
    delay(150);
    kickWatchdog();
  }
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    const char command = static_cast<char>(Serial.read());

    switch (command) {
    case 'S':
    case 's':
      g_detecting = false;
      g_counting = false;
      g_streaming = true;
      Serial.println("STREAMING");
      break;
    case 'P':
    case 'p':
      g_streaming = false;
      g_detecting = false;
      Serial.println("PAUSED");
      break;
    case 'F':
    case 'f':
      applyFaceExposure();
      break;
    case 'A':
    case 'a':
      applyAutoExposure();
      break;
    case 'C':
      g_streaming = false;
      g_detecting = false;
      g_counting = false;
      doSingleCount(true);
      break;
    case 'J':
    case 'j':
      g_streaming = false;
      g_detecting = false;
      g_counting = false;
      doJsonCount();
      break;
    case 'T':
    case 't':
      g_streaming = false;
      g_detecting = false;
      g_counting = false;
      doTimedCount();
      break;
    case 'M':
    case 'm':
      g_streaming = false;
      g_detecting = false;
      g_counting = false;
      printMemoryStatus();
      break;
    case 'K':
    case 'k':
      g_streaming = false;
      g_detecting = false;
      g_counting = true;
      Serial.println("COUNTING");
      break;
    case 'D':
    case 'd':
      g_streaming = false;
      g_counting = false;
      g_detecting = true;
      Serial.println("DETECTING");
      break;
    case 'X':
    case 'x':
      g_counting = false;
      g_detecting = false;
      Serial.println("STOPPED");
      break;
    case 'c':
      applyCalibratedExposure();
      break;
    case '?':
      printReady();
      break;
    default:
      break;
    }
  }
}

} // namespace

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.begin(kSerialBaud);
  const unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart < 5000)) {
    delay(10);
  }
  
  Serial.println("DEBUG: Starting setup");
  Serial.flush();

  initializeShieldPins();
  Serial.println("DEBUG: Shield initialized");
  Serial.flush();
  
  startWatchdog();
  Serial.println("DEBUG: Watchdog started");
  Serial.flush();

  if (!Camera.begin(kCameraResolution, GRAYSCALE, kCameraFps)) {
    fatalBlink("ERROR: failed to initialize OV7675 camera");
  }
  Serial.println("DEBUG: Camera initialized");
  Serial.flush();

  if (Camera.width() != kFrameWidth || Camera.height() != kFrameHeight) {
    Serial.print("DEBUG: Camera geometry mismatch: w=");
    Serial.print(Camera.width());
    Serial.print(" h=");
    Serial.print(Camera.height());
    Serial.print(" bpp=");
    Serial.println(Camera.bytesPerPixel());
    fatalBlink("ERROR: unexpected camera frame geometry");
  }
  Serial.println("DEBUG: Camera geometry OK");
  Serial.flush();

  initializeInferenceMap();

  applyAutoExposure();
  Serial.println("DEBUG: Auto exposure applied");
  Serial.flush();
  
  warmupCamera(kAutoWarmupFrames);
  Serial.println("DEBUG: Camera warmed up");
  Serial.flush();
  
  printReady();
}

void loop() {
  handleSerialCommands();
  kickWatchdog();

  if (g_counting) {
    doSingleCount(false);
    kickWatchdog();
    delay(kCountIntervalMs);
    return;
  }

  if (g_detecting) {
    doDetectionFrame();
    kickWatchdog();
    digitalWrite(LED_BUILTIN, (g_frameNumber & 0x01) ? HIGH : LOW);
    return;
  }

  if (!g_streaming) {
    delay(10);
    return;
  }

  Camera.readFrame(g_frame);
  writeFrameHeader();
  Serial.write(g_frame, kFrameBytes);
  Serial.flush();
  ++g_frameNumber;
  digitalWrite(LED_BUILTIN, (g_frameNumber & 0x01) ? HIGH : LOW);
  kickWatchdog();
}
