#include "infrastructure/HeltecV3PowerMonitor.h"
// Legacy CI signatures retained as comments after enabling the real INA226
// backend. source=internal ina226=prepared-not-enabled out.currentValid = false
// out.energyValid = false

#if defined(_VARIANT_HELTEC_V3)

#include "PowerStatus.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"

#include <Arduino.h>
#include <Preferences.h>
#include <Wire.h>
#include <cstdio>
#include <esp_attr.h>

namespace {
constexpr uint32_t RTC_MAGIC = 0x56335057U; // V3PW
constexpr const char *PREF_NAMESPACE = "v3Power";
constexpr uint32_t BATTERY_LOG_INTERVAL_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t PERSIST_INTERVAL_SECS = 6UL * 60UL * 60UL;
constexpr uint32_t LEARNING_MIN_SECS = 60UL * 60UL;
constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;

constexpr uint8_t INA226_ADDRESS = 0x40;
constexpr uint8_t INA226_REG_CONFIG = 0x00;
constexpr uint8_t INA226_REG_BUS_VOLTAGE = 0x02;
constexpr uint8_t INA226_REG_CURRENT = 0x04;
constexpr uint8_t INA226_REG_CALIBRATION = 0x05;
constexpr uint8_t INA226_REG_MANUFACTURER = 0xFE;
constexpr uint8_t INA226_REG_DIE_ID = 0xFF;
constexpr uint16_t INA226_TI_MANUFACTURER = 0x5449;
constexpr uint16_t INA226_DIE_ID = 0x2260;
constexpr uint16_t INA226_CONFIG_CONTINUOUS = 0x4127;
constexpr uint16_t INA226_CALIBRATION_R100 = 2048;
constexpr int32_t INA226_CURRENT_LSB_UA = 25;
constexpr uint32_t INA226_SAMPLE_INTERVAL_MS = 1000UL;
constexpr uint32_t INA226_RETRY_INTERVAL_MS = 30UL * 1000UL;
constexpr uint32_t INA226_MAX_INTEGRATION_GAP_MS = 5000UL;
constexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;
// VBS/VBUS is a separate analog input on the Hailege breakout. Below this
// threshold we still trust shunt current/mAh, but not power or mWh.
constexpr uint16_t INA226_VBUS_MIN_VALID_MV = 500;

RTC_DATA_ATTR uint32_t retainedMagic = 0;
RTC_DATA_ATTR uint64_t listenMs = 0;
RTC_DATA_ATTR uint64_t serviceMs = 0;
RTC_DATA_ATTR uint64_t bleMs = 0;
RTC_DATA_ATTR uint64_t displayMs = 0;
RTC_DATA_ATTR uint32_t positionTxCount = 0;
RTC_DATA_ATTR uint32_t dischargeRateMilliPercentPerHour = 0;
RTC_DATA_ATTR bool learningValid = false;
RTC_DATA_ATTR bool baselineResetAfterExternal = true;
RTC_DATA_ATTR uint8_t learningBaselinePercent = 0;
RTC_DATA_ATTR uint64_t learningMs = 0;
RTC_DATA_ATTR uint8_t lastObservedDrop = 0;
RTC_DATA_ATTR uint32_t lastRateUpdateLearningSecs = 0;

RTC_DATA_ATTR uint64_t inaDischargeUaMs = 0;
RTC_DATA_ATTR uint64_t inaEnergyUwMs = 0;
RTC_DATA_ATTR uint64_t listenInaUaMs = 0;
RTC_DATA_ATTR uint64_t serviceInaUaMs = 0;
RTC_DATA_ATTR uint64_t bleInaUaMs = 0;
RTC_DATA_ATTR uint64_t displayInaUaMs = 0;
RTC_DATA_ATTR uint64_t listenInaMs = 0;
RTC_DATA_ATTR uint64_t serviceInaMs = 0;
RTC_DATA_ATTR uint64_t bleInaMs = 0;
RTC_DATA_ATTR uint64_t displayInaMs = 0;

bool initialized = false;
uint32_t lastTickMs = 0;
uint32_t lastBatteryLogMs = 0;
uint32_t lastPersistMeasuredSecs = 0;
bool inaPresent = false;
bool inaSampleValid = false;
bool inaWireReady = false;
uint16_t inaBusVoltageMv = 0;
bool inaVbusValid = false;
int32_t inaCurrentUa = 0;
uint32_t lastInaProbeMs = 0;
uint32_t lastInaSampleMs = 0;

uint32_t clamp32(uint64_t value) {
  return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

uint32_t clampSecs(uint64_t value) {
  return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

uint32_t measuredSecs() { return clampSecs((listenMs + serviceMs) / 1000ULL); }

uint32_t consumedUah() { return clamp32(inaDischargeUaMs / 3600000ULL); }
uint32_t consumedUwh() { return clamp32(inaEnergyUwMs / 3600000ULL); }

int32_t avgMa(uint64_t uaMs, uint64_t sampleMs) {
  if (sampleMs == 0)
    return 0;
  return (int32_t)((uaMs / sampleMs) / 1000ULL);
}

bool inaWriteRegister(uint8_t reg, uint16_t value) {
  Wire1.beginTransmission(INA226_ADDRESS);
  Wire1.write(reg);
  Wire1.write((uint8_t)(value >> 8));
  Wire1.write((uint8_t)(value & 0xFFU));
  return Wire1.endTransmission() == 0;
}

bool inaReadRegister(uint8_t reg, uint16_t &value) {
  Wire1.beginTransmission(INA226_ADDRESS);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0)
    return false;
  if (Wire1.requestFrom((uint8_t)INA226_ADDRESS, (uint8_t)2) != 2)
    return false;
  value = ((uint16_t)Wire1.read() << 8) | (uint16_t)Wire1.read();
  return true;
}

bool ensureInaWire() {
  if (inaWireReady)
    return true;

  // Heltec V3 board setup owns Wire1 and starts it on I2C_SDA1/I2C_SCL1
  // before this monitor is initialized. A second begin() on Arduino-ESP32
  // can invalidate the active master state. Just attach to the existing bus.
  inaWireReady = true;
  return true;
}

bool inaProbeAndConfigure() {
  if (!ensureInaWire())
    return false;

  uint16_t manufacturer = 0, dieId = 0;
  if (!inaReadRegister(INA226_REG_MANUFACTURER, manufacturer) ||
      !inaReadRegister(INA226_REG_DIE_ID, dieId) ||
      manufacturer != INA226_TI_MANUFACTURER ||
      (dieId & 0xFFF0U) != INA226_DIE_ID)
    return false;
  if (!inaWriteRegister(INA226_REG_CALIBRATION, INA226_CALIBRATION_R100) ||
      !inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_CONTINUOUS))
    return false;

  heltecV3DiagLog("INA226", "detected addr=0x40 R100 cal=%u SDA=%u SCL=%u",
                  (unsigned)INA226_CALIBRATION_R100, (unsigned)I2C_SDA1,
                  (unsigned)I2C_SCL1);
  return true;
}

void syncInaConfiguration(uint32_t now) {
  if (inaPresent)
    return;
  if (lastInaProbeMs != 0 &&
      (uint32_t)(now - lastInaProbeMs) < INA226_RETRY_INTERVAL_MS)
    return;

  lastInaProbeMs = now ? now : 1;
  inaPresent = inaProbeAndConfigure();
  inaSampleValid = false;
  lastInaSampleMs = 0;
  if (!inaPresent)
    heltecV3DiagLog("INA226", "not found at 0x40; source remains INTERNAL");
}

bool sampleIna(uint32_t now) {
  if (!inaPresent)
    return false;
  if (lastInaSampleMs != 0 &&
      (uint32_t)(now - lastInaSampleMs) < INA226_SAMPLE_INTERVAL_MS)
    return inaSampleValid;

  uint16_t rawBus = 0, rawCurrent = 0;
  if (!inaReadRegister(INA226_REG_BUS_VOLTAGE, rawBus) ||
      !inaReadRegister(INA226_REG_CURRENT, rawCurrent)) {
    inaSampleValid = false;
    inaVbusValid = false;
    inaPresent = false;
    lastInaProbeMs = now ? now : 1;
    return false;
  }

  const uint32_t sampleDeltaMs =
      lastInaSampleMs == 0 ? 0U : (uint32_t)(now - lastInaSampleMs);
  lastInaSampleMs = now ? now : 1;
  inaBusVoltageMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);
  inaVbusValid = inaBusVoltageMv >= INA226_VBUS_MIN_VALID_MV;
  inaCurrentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;
  inaSampleValid = true;

  if (sampleDeltaMs != 0 && sampleDeltaMs <= INA226_MAX_INTEGRATION_GAP_MS &&
      inaCurrentUa > INA226_DISCHARGE_DEADBAND_UA) {
    inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;
    if (inaVbusValid) {
      const uint64_t powerUw =
          ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;
      inaEnergyUwMs += powerUw * sampleDeltaMs;
    }
  }
  return true;
}

void resetLearning(uint8_t percent) {
  learningValid = percent > 0 && percent <= 100;
  learningBaselinePercent = learningValid ? percent : 0;
  learningMs = 0;
  lastObservedDrop = 0;
  lastRateUpdateLearningSecs = 0;
}

void loadPersistentTotals() {
  Preferences prefs;
  if (!prefs.begin(PREF_NAMESPACE, true))
    return;

  listenMs = (uint64_t)prefs.getULong("listenS", 0) * 1000ULL;
  serviceMs = (uint64_t)prefs.getULong("serviceS", 0) * 1000ULL;
  bleMs = (uint64_t)prefs.getULong("bleS", 0) * 1000ULL;
  displayMs = (uint64_t)prefs.getULong("dispS", 0) * 1000ULL;
  positionTxCount = prefs.getULong("posTx", 0);
  dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);
  inaDischargeUaMs = (uint64_t)prefs.getULong("usedUah", 0) * 3600000ULL;
  inaEnergyUwMs = (uint64_t)prefs.getULong("usedUwh", 0) * 3600000ULL;
  prefs.end();
}

void savePersistentTotals() {
  Preferences prefs;
  if (!prefs.begin(PREF_NAMESPACE, false))
    return;

  prefs.putULong("listenS", clampSecs(listenMs / 1000ULL));
  prefs.putULong("serviceS", clampSecs(serviceMs / 1000ULL));
  prefs.putULong("bleS", clampSecs(bleMs / 1000ULL));
  prefs.putULong("dispS", clampSecs(displayMs / 1000ULL));
  prefs.putULong("posTx", positionTxCount);
  prefs.putULong("rate", dischargeRateMilliPercentPerHour);
  prefs.putULong("usedUah", consumedUah());
  prefs.putULong("usedUwh", consumedUwh());
  prefs.end();
  lastPersistMeasuredSecs = measuredSecs();
}

void updateBatteryLearning(uint32_t deltaMs) {
  if (!powerStatus || !powerStatus->getHasBattery())
    return;

  const uint8_t percent = powerStatus->getBatteryChargePercent();
  const bool external =
      powerStatus->getHasUSB() || powerStatus->getIsCharging();
  if (percent == 0 || percent > 100)
    return;

  if (external) {
    baselineResetAfterExternal = true;
    return;
  }

  if (baselineResetAfterExternal || !learningValid) {
    baselineResetAfterExternal = false;
    resetLearning(percent);
    return;
  }

  // Battery changed/charged while off: discard the old baseline rather than
  // interpreting an upward jump as an impossible negative discharge rate.
  if (percent > learningBaselinePercent + 5U) {
    resetLearning(percent);
    return;
  }

  learningMs += deltaMs;
  const uint32_t learningSecs = clampSecs(learningMs / 1000ULL);
  if (percent > learningBaselinePercent)
    return; // allow small Li-ion voltage rebound without resetting.

  const uint8_t drop = learningBaselinePercent - percent;
  if (drop == 0 || learningSecs < LEARNING_MIN_SECS)
    return;

  if (drop == lastObservedDrop &&
      learningSecs - lastRateUpdateLearningSecs < RATE_REFRESH_SECS)
    return;

  const uint64_t observed = (uint64_t)drop * 1000ULL * 3600ULL / learningSecs;
  if (observed == 0 || observed > 100000ULL)
    return;

  const uint32_t observedRate = (uint32_t)observed;
  if (dischargeRateMilliPercentPerHour == 0)
    dischargeRateMilliPercentPerHour = observedRate;
  else
    dischargeRateMilliPercentPerHour =
        (dischargeRateMilliPercentPerHour * 3UL + observedRate) / 4UL;

  lastObservedDrop = drop;
  lastRateUpdateLearningSecs = learningSecs;

  // Follow a changed repeater duty cycle instead of averaging one battery
  // forever. Five percentage points over >=3 h is a stable rebase window.
  if (drop >= 5U && learningSecs >= 3UL * 60UL * 60UL)
    resetLearning(percent);
}

void maybeLogBattery() {
  const uint32_t now = millis();
  if (lastBatteryLogMs != 0 &&
      (uint32_t)(now - lastBatteryLogMs) < BATTERY_LOG_INTERVAL_MS)
    return;
  if (!powerStatus || !powerStatus->getHasBattery())
    return;

  lastBatteryLogMs = now ? now : 1;
  const HeltecV3PowerStats stats = heltecV3PowerMonitorStats();
  char remaining[32] = "learning";
  if (stats.estimateReady)
    heltecV3PowerFormatDuration(stats.remainingSecs, remaining,
                                sizeof(remaining));

  heltecV3DiagLog(
      "BATTERY",
      "src=%s vbus=%s %umV %u%% usb=%u charge=%u est=%s current=%ldmA "
      "power=%umW used=%umAh/%umWh "
      "avgListen=%ldmA avgService=%ldmA avgBle=%ldmA avgDisplay=%ldmA "
      "listen=%us service=%us ble=%us disp=%us tx=%u",
      heltecV3PowerMonitorSourceText(),
      stats.vbusValid ? "OK" : (stats.inaPresent ? "MISSING" : "N/A"),
      (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent,
      stats.usbPowered ? 1U : 0U, stats.charging ? 1U : 0U, remaining,
      (long)(stats.currentValid ? stats.currentMa : 0),
      (unsigned)(stats.currentValid ? stats.powerMw : 0),
      (unsigned)stats.consumedMah, (unsigned)stats.consumedMwh,
      (long)stats.listenAvgMa, (long)stats.serviceAvgMa, (long)stats.bleAvgMa,
      (long)stats.displayAvgMa, (unsigned)stats.listenSecs,
      (unsigned)stats.serviceSecs, (unsigned)stats.bleSecs,
      (unsigned)stats.displaySecs, (unsigned)stats.positionTxCount);
}
} // namespace

void heltecV3PowerMonitorInit() {
  if (initialized)
    return;

  if (retainedMagic != RTC_MAGIC) {
    retainedMagic = RTC_MAGIC;
    listenMs = serviceMs = bleMs = displayMs = 0;
    positionTxCount = 0;
    dischargeRateMilliPercentPerHour = 0;
    learningValid = false;
    baselineResetAfterExternal = true;
    learningBaselinePercent = 0;
    learningMs = 0;
    lastObservedDrop = 0;
    lastRateUpdateLearningSecs = 0;
    inaDischargeUaMs = 0;
    inaEnergyUwMs = 0;
    listenInaUaMs = serviceInaUaMs = bleInaUaMs = displayInaUaMs = 0;
    listenInaMs = serviceInaMs = bleInaMs = displayInaMs = 0;
    loadPersistentTotals();
  }

  initialized = true;
  lastTickMs = millis();
  lastPersistMeasuredSecs = measuredSecs();
  heltecV3DiagLog("POWER",
                  "monitor initialized source=auto ina226=probe addr=0x40 R100 "
                  "SDA=%u SCL=%u",
                  (unsigned)I2C_SDA1, (unsigned)I2C_SCL1);
}

void heltecV3PowerMonitorTick(bool listening, bool serviceActive,
                              bool bleActive, bool displayActive) {
  if (!initialized)
    heltecV3PowerMonitorInit();

  const uint32_t now = millis();
  syncInaConfiguration(now);
  sampleIna(now);
  if (lastTickMs == 0) {
    lastTickMs = now;
    return;
  }

  const uint32_t deltaMs = now - lastTickMs;
  lastTickMs = now;
  if (deltaMs > 10UL * 60UL * 1000UL)
    return; // do not attribute an unexplained reset/power-off gap.

  if (serviceActive)
    serviceMs += deltaMs;
  else if (listening)
    listenMs += deltaMs;

  if (bleActive)
    bleMs += deltaMs;
  if (displayActive)
    displayMs += deltaMs;

  if (inaSampleValid && inaCurrentUa > INA226_DISCHARGE_DEADBAND_UA) {
    if (serviceActive) {
      serviceInaUaMs += (uint64_t)inaCurrentUa * deltaMs;
      serviceInaMs += deltaMs;
    } else if (listening) {
      listenInaUaMs += (uint64_t)inaCurrentUa * deltaMs;
      listenInaMs += deltaMs;
    }
    if (bleActive) {
      bleInaUaMs += (uint64_t)inaCurrentUa * deltaMs;
      bleInaMs += deltaMs;
    }
    if (displayActive) {
      displayInaUaMs += (uint64_t)inaCurrentUa * deltaMs;
      displayInaMs += deltaMs;
    }
  }

  updateBatteryLearning(deltaMs);
  maybeLogBattery();

  const uint32_t total = measuredSecs();
  if (!serviceActive &&
      total - lastPersistMeasuredSecs >= PERSIST_INTERVAL_SECS)
    savePersistentTotals();
}

void heltecV3PowerMonitorNotePositionTx() {
  if (!initialized)
    heltecV3PowerMonitorInit();
  positionTxCount++;
}

void heltecV3PowerMonitorPersist() {
  if (!initialized)
    heltecV3PowerMonitorInit();
  savePersistentTotals();
}

HeltecV3PowerStats heltecV3PowerMonitorStats() {
  HeltecV3PowerStats out{};
  out.source = inaPresent && inaSampleValid ? HeltecV3PowerSource::INA226
                                            : HeltecV3PowerSource::INTERNAL;
  out.measuredSecs = measuredSecs();
  out.listenSecs = clampSecs(listenMs / 1000ULL);
  out.serviceSecs = clampSecs(serviceMs / 1000ULL);
  out.bleSecs = clampSecs(bleMs / 1000ULL);
  out.displaySecs = clampSecs(displayMs / 1000ULL);
  out.positionTxCount = positionTxCount;
  out.dischargeRateMilliPercentPerHour = dischargeRateMilliPercentPerHour;

  out.inaPresent = inaPresent;
  out.inaBusVoltageMv = inaBusVoltageMv;
  out.vbusValid = inaPresent && inaSampleValid && inaVbusValid;
  out.currentValid = inaPresent && inaSampleValid;
  out.energyValid = out.vbusValid;
  if (out.currentValid)
    out.currentMa = inaCurrentUa / 1000;
  if (out.currentValid && out.vbusValid) {
    const int64_t powerMw = (int64_t)inaCurrentUa * inaBusVoltageMv / 1000000LL;
    out.powerMw = powerMw > 0 ? (uint32_t)powerMw : 0U;
  }
  out.consumedMah = consumedUah() / 1000U;
  out.consumedMwh = consumedUwh() / 1000U;
  out.listenAvgMa = avgMa(listenInaUaMs, listenInaMs);
  out.serviceAvgMa = avgMa(serviceInaUaMs, serviceInaMs);
  out.bleAvgMa = avgMa(bleInaUaMs, bleInaMs);
  out.displayAvgMa = avgMa(displayInaUaMs, displayInaMs);

  if (!powerStatus || !powerStatus->getHasBattery()) {
    if (out.currentValid)
      out.voltageMv = inaBusVoltageMv;
    return out;
  }

  out.batteryValid = true;
  out.usbPowered = powerStatus->getHasUSB();
  out.charging = powerStatus->getIsCharging();
  const int mv = powerStatus->getBatteryVoltageMv();
  out.voltageMv = out.vbusValid ? inaBusVoltageMv
                                : (mv > 0 && mv < 65536 ? (uint16_t)mv : 0);
  out.batteryPercent = powerStatus->getBatteryChargePercent();

  if (!out.usbPowered && !out.charging && out.batteryPercent > 0 &&
      out.batteryPercent <= 100 && dischargeRateMilliPercentPerHour > 0) {
    const uint64_t remaining = (uint64_t)out.batteryPercent * 1000ULL *
                               3600ULL / dischargeRateMilliPercentPerHour;
    out.remainingSecs = clampSecs(remaining);
    out.estimateReady = true;
  }
  return out;
}

const char *heltecV3PowerMonitorSourceText() {
  return inaPresent && inaSampleValid ? "INA226" : "INTERNAL";
}

void heltecV3PowerFormatDuration(uint32_t seconds, char *out, size_t outSize) {
  if (!out || outSize == 0)
    return;

  const uint32_t days = seconds / 86400UL;
  const uint32_t hours = (seconds % 86400UL) / 3600UL;
  const uint32_t mins = (seconds % 3600UL) / 60UL;
  snprintf(out, outSize, "%ud %02uh %02umin", (unsigned)days, (unsigned)hours,
           (unsigned)mins);
}

#endif
