#include <Arduino.h>
#include <TinyMLShield.h>
#include <Wire.h>

#if defined(ARDUINO_ARCH_MBED)
#include <mbed.h>
#endif

namespace {

constexpr unsigned long kSerialBaud = 921600;
constexpr uint8_t kCameraFps = 5;
constexpr uint16_t kFrameWidth = 160;
constexpr uint16_t kFrameHeight = 120;
constexpr uint8_t kBytesPerPixel = 1;
constexpr uint8_t kFormatGrayscale = 0;
constexpr uint32_t kFrameBytes =
    static_cast<uint32_t>(kFrameWidth) * kFrameHeight * kBytesPerPixel;
constexpr uint8_t kFrameMagic[] = {'O', 'V', 'F', '1'};
constexpr uint32_t kWatchdogTimeoutMs = 8000;
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
static bool g_streaming = false;
static uint32_t g_frameNumber = 0;

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
      "commands: S=start, P=pause, F=face exposure, A=auto exposure, C=calibrated exposure, ?=status");
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
      g_streaming = true;
      Serial.println("STREAMING");
      break;
    case 'P':
    case 'p':
      g_streaming = false;
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

  initializeShield();
  Serial.println("DEBUG: Shield initialized");
  Serial.flush();
  
  startWatchdog();
  Serial.println("DEBUG: Watchdog started");
  Serial.flush();

  if (!Camera.begin(QQVGA, GRAYSCALE, kCameraFps, OV7675)) {
    fatalBlink("ERROR: failed to initialize OV7675 camera");
  }
  Serial.println("DEBUG: Camera initialized");
  Serial.flush();

  if (Camera.width() != kFrameWidth || Camera.height() != kFrameHeight ||
      Camera.bytesPerPixel() != kBytesPerPixel) {
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
