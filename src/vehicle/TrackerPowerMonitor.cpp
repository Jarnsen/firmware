#include "vehicle/TrackerPowerMonitor.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "DebugConfiguration.h"
#include "PowerStatus.h"
#include "gps/RTC.h"
#include "vehicle/TrackerDiagnosticLog.h"
#include "vehicle/TrackerServiceSettings.h"

#include <Arduino.h>
#include <Preferences.h>
#include <Wire.h>
#include <cstdio>
#include <esp_attr.h>
#include <esp_sleep.h>
#include <esp_timer.h>

namespace
{
constexpr uint32_t RTC_MAGIC = 0x54525057U;
constexpr const char *PREF_NAMESPACE = "trkPower";
constexpr uint32_t BATTERY_LOG_INTERVAL_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t PERSIST_INTERVAL_SECS = 6UL * 60UL * 60UL;
constexpr uint32_t LEARNING_MIN_SECS = 60UL * 60UL;
constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;

constexpr uint8_t INA226_DEFAULT_ADDRESS = 0x40;
constexpr uint8_t INA226_SCAN_FIRST = 0x40;
constexpr uint8_t INA226_SCAN_LAST = 0x4F;
constexpr uint8_t INA226_REG_CONFIG = 0x00;
constexpr uint8_t INA226_REG_BUS_VOLTAGE = 0x02;
constexpr uint8_t INA226_REG_CURRENT = 0x04;
constexpr uint8_t INA226_REG_CALIBRATION = 0x05;
constexpr uint8_t INA226_REG_MANUFACTURER = 0xFE;
constexpr uint8_t INA226_REG_DIE_ID = 0xFF;
constexpr uint16_t INA226_TI_MANUFACTURER = 0x5449;
constexpr uint16_t INA226_DIE_ID = 0x2260;
constexpr uint16_t INA226_CONFIG_CONTINUOUS = 0x4127;
constexpr uint16_t INA226_CONFIG_POWER_DOWN = 0x4120;
// One-shot shunt+bus conversion with 8.244 ms per channel. The INA226
// performs this conversion after the CPU enters sleep and then returns to
// power-down by itself. No CPU wake is created only for measurement.
constexpr uint16_t INA226_CONFIG_SLEEP_SINGLE = 0x41FB;
constexpr uint16_t INA226_CALIBRATION_R100 = 2048;
constexpr int32_t INA226_CURRENT_LSB_UA = 25;
constexpr uint32_t INA226_SAMPLE_INTERVAL_MS = 250;
constexpr uint32_t INA226_RETRY_INTERVAL_MS = 30UL * 1000UL;
constexpr uint32_t INA226_MAX_INTEGRATION_GAP_MS = 5000UL;
constexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;
// Hailege breakout exposes VBS/VBUS separately. Current/mAh come from the
// shunt and remain valid without VBS; power/mWh require a plausible bus input.
constexpr uint16_t INA226_VBUS_MIN_VALID_MV = 500;
constexpr int32_t INA226_SLEEP_MIN_UA = 50;
constexpr int64_t INA226_LIGHT_SLEEP_REFRESH_US = 15LL * 60LL * 1000000LL;
constexpr int64_t INA226_SLEEP_SHOT_MIN_US = 20000LL;

constexpr uint8_t CAPACITY_MIN_DROP_PERCENT = 30;
constexpr uint32_t CAPACITY_MIN_USED_UAH = 50000UL;
constexpr uint32_t CAPACITY_MIN_MAH = 200;
constexpr uint32_t CAPACITY_MAX_MAH = 100000;

RTC_DATA_ATTR uint32_t retainedMagic = 0;
RTC_DATA_ATTR uint64_t movingMs = 0;
RTC_DATA_ATTR uint64_t parkedMs = 0;
RTC_DATA_ATTR uint64_t gnssMs = 0;
RTC_DATA_ATTR uint64_t bleMs = 0;
RTC_DATA_ATTR uint64_t displayMs = 0;
RTC_DATA_ATTR uint64_t otherMs = 0;
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
RTC_DATA_ATTR uint32_t learnedCapacityMah = 0;
RTC_DATA_ATTR uint16_t capacityCycles = 0;
RTC_DATA_ATTR uint8_t capacityConfidence = 0;
RTC_DATA_ATTR bool capacityWindowValid = false;
RTC_DATA_ATTR bool capacityResetAfterExternal = true;
RTC_DATA_ATTR uint8_t capacityBaselinePercent = 0;
RTC_DATA_ATTR uint32_t capacityBaselineUsedUah = 0;

// Sleep energy stays separate from continuously measured awake energy.
// It is estimated from a real INA226 sample captured while the ESP is asleep.
RTC_DATA_ATTR uint64_t inaSleepUaMs = 0;
RTC_DATA_ATTR uint64_t inaSleepUwMs = 0;
RTC_DATA_ATTR uint64_t lightSleepMs = 0;
RTC_DATA_ATTR uint64_t deepSleepMs = 0;
RTC_DATA_ATTR int32_t lightSleepBaselineUa = 0;
RTC_DATA_ATTR uint16_t lightSleepBaselineMv = 0;
RTC_DATA_ATTR int32_t deepSleepLastUa = 0;
RTC_DATA_ATTR uint16_t deepSleepLastMv = 0;
RTC_DATA_ATTR bool deepSleepShotPending = false;
RTC_DATA_ATTR uint32_t deepSleepPlannedSecs = 0;
RTC_DATA_ATTR uint32_t deepSleepStartEpoch = 0;

bool initialized = false;
uint32_t lastTickMs = 0;
uint32_t lastBatteryLogMs = 0;
uint32_t lastPersistMeasuredSecs = 0;
bool inaPresent = false;
bool inaSampleValid = false;
bool inaWireReady = false;
uint8_t inaAddress = INA226_DEFAULT_ADDRESS;
uint8_t inaPersistedAddress = 0xFF;
uint16_t inaBusVoltageMv = 0;
int32_t inaCurrentUa = 0;
uint32_t lastInaProbeMs = 0;
uint32_t lastInaSampleMs = 0;

bool lightSleepIntervalPending = false;
bool lightSleepShotPending = false;
int64_t lightSleepStartedUs = 0;
int64_t lastLightSleepProfileUs = 0;

uint32_t clamp32(uint64_t value)
{
    return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}
uint32_t clampSecs(uint64_t value)
{
    return clamp32(value);
}
uint32_t measuredSecs()
{
    return clampSecs((movingMs + parkedMs + otherMs) / 1000ULL);
}
bool inaAddressInRange(uint8_t address)
{
    return address >= INA226_SCAN_FIRST && address <= INA226_SCAN_LAST;
}
bool inaVbusIsValid(uint16_t busMv)
{
    return busMv >= INA226_VBUS_MIN_VALID_MV;
}
uint32_t dischargedUah()
{
    return clamp32(inaDischargeUaMs / 3600000ULL);
}
uint32_t dischargedUwh()
{
    return clamp32(inaEnergyUwMs / 3600000ULL);
}
uint32_t sleepEstimatedUah()
{
    return clamp32(inaSleepUaMs / 3600000ULL);
}
uint32_t sleepEstimatedUwh()
{
    return clamp32(inaSleepUwMs / 3600000ULL);
}
uint32_t totalDischargedUah()
{
    return clamp32((uint64_t)dischargedUah() + sleepEstimatedUah());
}
uint32_t totalDischargedUwh()
{
    return clamp32((uint64_t)dischargedUwh() + sleepEstimatedUwh());
}

void resetLearning(uint8_t percent)
{
    learningValid = percent > 0 && percent <= 100;
    learningBaselinePercent = learningValid ? percent : 0;
    learningMs = 0;
    lastObservedDrop = 0;
    lastRateUpdateLearningSecs = 0;
}

bool inaWriteRegisterAt(uint8_t address, uint8_t reg, uint16_t value)
{
    Wire.beginTransmission(address);
    Wire.write(reg);
    Wire.write((uint8_t)(value >> 8));
    Wire.write((uint8_t)(value & 0xFFU));
    return Wire.endTransmission() == 0;
}

bool inaReadRegisterAt(uint8_t address, uint8_t reg, uint16_t &value)
{
    Wire.beginTransmission(address);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0)
        return false;
    if (Wire.requestFrom(address, (uint8_t)2) != 2)
        return false;
    value = ((uint16_t)Wire.read() << 8) | (uint16_t)Wire.read();
    return true;
}

bool inaWriteRegister(uint8_t reg, uint16_t value)
{
    return inaWriteRegisterAt(inaAddress, reg, value);
}

bool inaReadRegister(uint8_t reg, uint16_t &value)
{
    return inaReadRegisterAt(inaAddress, reg, value);
}

bool ensureInaWire()
{
    if (inaWireReady)
        return true;

    // Meshtastic owns and initializes the shared board I2C bus before the tracker policy starts.
    inaWireReady = true;
    LOG_INFO("INA226: reuse existing I2C bus SDA=%u SCL=%u", (unsigned)SDA, (unsigned)SCL);
    trackerDiagLog("INA226", "reuse existing I2C bus SDA=%u SCL=%u", (unsigned)SDA, (unsigned)SCL);
    return true;
}

uint8_t inaProbeAddressAck(uint8_t address)
{
    Wire.beginTransmission(address);
    return Wire.endTransmission();
}

bool inaReadIdentityAt(uint8_t address, uint16_t &manufacturer, uint16_t &dieId)
{
    return inaReadRegisterAt(address, INA226_REG_MANUFACTURER, manufacturer) &&
           inaReadRegisterAt(address, INA226_REG_DIE_ID, dieId);
}

bool inaIdentityMatches(uint16_t manufacturer, uint16_t dieId)
{
    return manufacturer == INA226_TI_MANUFACTURER && (dieId & 0xFFF0U) == INA226_DIE_ID;
}

void loadInaAddressPreference()
{
    inaAddress = INA226_DEFAULT_ADDRESS;
    inaPersistedAddress = 0xFF;

    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, true))
        return;
    const uint8_t saved = prefs.getUChar("inaAddr", 0xFF);
    prefs.end();

    if (!inaAddressInRange(saved))
        return;

    inaAddress = saved;
    inaPersistedAddress = saved;
    if (trackerIna226Enabled())
        LOG_INFO("INA226: loaded saved address 0x%02X", (unsigned)saved);
}

void saveInaAddressPreference(uint8_t address)
{
    if (!inaAddressInRange(address) || inaPersistedAddress == address)
        return;

    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putUChar("inaAddr", address);
    prefs.end();
    inaPersistedAddress = address;
}

bool inaConfigureAt(uint8_t address)
{
    const uint8_t ack = inaProbeAddressAck(address);
    if (ack != 0) {
        LOG_WARN("INA226: ACK FAIL addr=0x%02X code=%u", (unsigned)address, (unsigned)ack);
        trackerDiagLog("INA226", "ACK FAIL addr=0x%02X code=%u", (unsigned)address, (unsigned)ack);
        return false;
    }

    uint16_t manufacturer = 0;
    uint16_t dieId = 0;
    if (!inaReadIdentityAt(address, manufacturer, dieId)) {
        LOG_WARN("INA226: identity read failed addr=0x%02X", (unsigned)address);
        trackerDiagLog("INA226", "identity read failed addr=0x%02X", (unsigned)address);
        return false;
    }

    LOG_INFO("INA226: identity addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address, (unsigned)manufacturer,
             (unsigned)dieId);
    trackerDiagLog("INA226", "identity addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address,
                   (unsigned)manufacturer, (unsigned)dieId);

    if (!inaIdentityMatches(manufacturer, dieId)) {
        LOG_WARN("INA226: wrong device addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address, (unsigned)manufacturer,
                 (unsigned)dieId);
        trackerDiagLog("INA226", "wrong device addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address,
                       (unsigned)manufacturer, (unsigned)dieId);
        return false;
    }

    if (!inaWriteRegisterAt(address, INA226_REG_CALIBRATION, INA226_CALIBRATION_R100)) {
        LOG_WARN("INA226: calibration write failed addr=0x%02X", (unsigned)address);
        trackerDiagLog("INA226", "calibration write failed addr=0x%02X", (unsigned)address);
        return false;
    }
    if (!inaWriteRegisterAt(address, INA226_REG_CONFIG, INA226_CONFIG_CONTINUOUS)) {
        LOG_WARN("INA226: config write failed addr=0x%02X", (unsigned)address);
        trackerDiagLog("INA226", "config write failed addr=0x%02X", (unsigned)address);
        return false;
    }

    inaAddress = address;
    const bool addressChanged = inaPersistedAddress != address;
    if (addressChanged) {
        saveInaAddressPreference(address);
        LOG_INFO("INA226: auto-selected address 0x%02X (saved)", (unsigned)address);
        trackerDiagLog("INA226", "auto-selected address 0x%02X saved=1", (unsigned)address);
    } else {
        LOG_INFO("INA226: using saved address 0x%02X", (unsigned)address);
        trackerDiagLog("INA226", "using saved address 0x%02X", (unsigned)address);
    }

    LOG_INFO("INA226: READY addr=0x%02X MFG=0x%04X DIE=0x%04X R100 cal=%u", (unsigned)address,
             (unsigned)manufacturer, (unsigned)dieId, (unsigned)INA226_CALIBRATION_R100);
    trackerDiagLog("INA226", "READY addr=0x%02X MFG=0x%04X DIE=0x%04X R100 cal=%u SDA=%u SCL=%u", (unsigned)address,
                   (unsigned)manufacturer, (unsigned)dieId, (unsigned)INA226_CALIBRATION_R100, (unsigned)SDA, (unsigned)SCL);
    return true;
}

bool inaScanForUniqueDevice(uint8_t &foundAddress)
{
    LOG_INFO("INA226: auto-scan 0x%02X-0x%02X start", (unsigned)INA226_SCAN_FIRST, (unsigned)INA226_SCAN_LAST);
    trackerDiagLog("INA226", "auto-scan 0x%02X-0x%02X start", (unsigned)INA226_SCAN_FIRST, (unsigned)INA226_SCAN_LAST);

    uint8_t responders = 0;
    uint8_t matches = 0;
    uint8_t lastMatch = INA226_DEFAULT_ADDRESS;

    for (uint8_t address = INA226_SCAN_FIRST; address <= INA226_SCAN_LAST; ++address) {
        const uint8_t ack = inaProbeAddressAck(address);
        if (ack != 0)
            continue;

        responders++;
        uint16_t manufacturer = 0;
        uint16_t dieId = 0;
        if (!inaReadIdentityAt(address, manufacturer, dieId)) {
            LOG_INFO("INA226: scan ACK addr=0x%02X IDs=unreadable", (unsigned)address);
            trackerDiagLog("INA226", "scan ACK addr=0x%02X IDs=unreadable", (unsigned)address);
            continue;
        }

        if (inaIdentityMatches(manufacturer, dieId)) {
            matches++;
            lastMatch = address;
            LOG_INFO("INA226: scan MATCH addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address,
                     (unsigned)manufacturer, (unsigned)dieId);
            trackerDiagLog("INA226", "scan MATCH addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address,
                           (unsigned)manufacturer, (unsigned)dieId);
        } else if (address == 0x44) {
            LOG_INFO("INA226: scan other addr=0x44 MFG=0x%04X DIE=0x%04X board OPT3001 address", (unsigned)manufacturer,
                     (unsigned)dieId);
            trackerDiagLog("INA226", "scan other addr=0x44 MFG=0x%04X DIE=0x%04X board=OPT3001", (unsigned)manufacturer,
                           (unsigned)dieId);
        } else {
            LOG_INFO("INA226: scan other addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address, (unsigned)manufacturer,
                     (unsigned)dieId);
            trackerDiagLog("INA226", "scan other addr=0x%02X MFG=0x%04X DIE=0x%04X", (unsigned)address,
                           (unsigned)manufacturer, (unsigned)dieId);
        }
    }

    if (matches == 1) {
        foundAddress = lastMatch;
        LOG_INFO("INA226: auto-scan selected unique device at 0x%02X responders=%u", (unsigned)foundAddress,
                 (unsigned)responders);
        trackerDiagLog("INA226", "auto-scan selected unique device at 0x%02X responders=%u", (unsigned)foundAddress,
                       (unsigned)responders);
        return true;
    }

    if (matches == 0) {
        LOG_WARN("INA226: auto-scan found no INA226 in 0x%02X-0x%02X responders=%u", (unsigned)INA226_SCAN_FIRST,
                 (unsigned)INA226_SCAN_LAST, (unsigned)responders);
        trackerDiagLog("INA226", "auto-scan found no INA226 in 0x%02X-0x%02X responders=%u", (unsigned)INA226_SCAN_FIRST,
                       (unsigned)INA226_SCAN_LAST, (unsigned)responders);
    } else {
        LOG_WARN("INA226: auto-scan found %u INA226 devices; automatic selection refused", (unsigned)matches);
        trackerDiagLog("INA226", "auto-scan found %u INA226 devices automatic-selection=refused", (unsigned)matches);
    }
    return false;
}

bool readInaInstant(int32_t &currentUa, uint16_t &busMv)
{
    if (!ensureInaWire())
        return false;

    uint16_t manufacturer = 0, dieId = 0, rawBus = 0, rawCurrent = 0;
    if (!inaReadRegister(INA226_REG_MANUFACTURER, manufacturer) || !inaReadRegister(INA226_REG_DIE_ID, dieId) ||
        !inaIdentityMatches(manufacturer, dieId) || !inaReadRegister(INA226_REG_BUS_VOLTAGE, rawBus) ||
        !inaReadRegister(INA226_REG_CURRENT, rawCurrent))
        return false;

    busMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);
    currentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;
    return true;
}

void addSleepEstimate(int32_t currentUa, uint16_t busMv, uint64_t durationMs, bool deep)
{
    if (durationMs == 0)
        return;

    if (deep)
        deepSleepMs += durationMs;
    else
        lightSleepMs += durationMs;

    if (currentUa <= INA226_SLEEP_MIN_UA)
        return;

    inaSleepUaMs += (uint64_t)currentUa * durationMs;
    if (inaVbusIsValid(busMv)) {
        const uint64_t powerUw = ((uint64_t)currentUa * busMv) / 1000ULL;
        inaSleepUwMs += powerUw * durationMs;
    }
}

void recoverDeepSleepShot()
{
    if (!deepSleepShotPending)
        return;

    const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    uint32_t durationSecs = 0;
    if (cause == ESP_SLEEP_WAKEUP_TIMER) {
        durationSecs = deepSleepPlannedSecs;
    } else if (cause == ESP_SLEEP_WAKEUP_EXT0
#if defined(ESP_SLEEP_WAKEUP_GPIO)
               || cause == ESP_SLEEP_WAKEUP_GPIO
#endif
    ) {
        const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
        if (deepSleepStartEpoch != 0 && nowEpoch >= deepSleepStartEpoch) {
            durationSecs = nowEpoch - deepSleepStartEpoch;
            if (deepSleepPlannedSecs != 0 && durationSecs > deepSleepPlannedSecs)
                durationSecs = deepSleepPlannedSecs;
        }
    }

    int32_t currentUa = 0;
    uint16_t busMv = 0;
    const bool sampleOk = trackerIna226Enabled() && readInaInstant(currentUa, busMv);
    if (sampleOk) {
        deepSleepLastUa = currentUa;
        deepSleepLastMv = busMv;
        if (durationSecs != 0) {
            addSleepEstimate(currentUa, busMv, (uint64_t)durationSecs * 1000ULL, true);
            trackerDiagLog("POWER_SLEEP",
                           "role=TAK_TRACKER mode=deep sample=%lduA %umV vbus=%s "
                           "duration=%us estimate=sample_x_duration",
                           (long)currentUa, (unsigned)busMv, inaVbusIsValid(busMv) ? "OK" : "MISSING", (unsigned)durationSecs);
        } else {
            trackerDiagLog("POWER_SLEEP",
                           "role=TAK_TRACKER mode=deep sample=%lduA %umV vbus=%s "
                           "duration=unknown estimate=not_integrated",
                           (long)currentUa, (unsigned)busMv, inaVbusIsValid(busMv) ? "OK" : "MISSING");
        }
    } else {
        trackerDiagLog("POWER_SLEEP", "role=TAK_TRACKER mode=deep "
                                      "sample=unavailable estimate=not_integrated");
    }

    deepSleepShotPending = false;
    deepSleepPlannedSecs = 0;
    deepSleepStartEpoch = 0;
    inaPresent = false;
    inaSampleValid = false;
    lastInaProbeMs = 0;
    lastInaSampleMs = 0;
}

void inaPowerDown()
{
    if (inaPresent)
        inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_POWER_DOWN);
    inaSampleValid = false;
    lastInaSampleMs = 0;
}

bool inaProbeAndConfigure()
{
    if (!ensureInaWire())
        return false;

    const bool preferredIsSaved = inaPersistedAddress == inaAddress;
    LOG_INFO("INA226: CONFIG=ON preferred=0x%02X source=%s SDA=%u SCL=%u", (unsigned)inaAddress,
             preferredIsSaved ? "saved" : "default", (unsigned)SDA, (unsigned)SCL);
    trackerDiagLog("INA226", "CONFIG=ON preferred=0x%02X source=%s SDA=%u SCL=%u", (unsigned)inaAddress,
                   preferredIsSaved ? "saved" : "default", (unsigned)SDA, (unsigned)SCL);

    if (inaConfigureAt(inaAddress))
        return true;

    uint8_t foundAddress = INA226_DEFAULT_ADDRESS;
    if (!inaScanForUniqueDevice(foundAddress))
        return false;

    if (foundAddress != inaAddress)
        LOG_INFO("INA226: switching candidate 0x%02X -> 0x%02X", (unsigned)inaAddress, (unsigned)foundAddress);
    return inaConfigureAt(foundAddress);
}

void syncInaConfiguration(uint32_t now)
{
    if (!trackerIna226Enabled()) {
        if (inaPresent)
            inaPowerDown();
        inaPresent = false;
        inaSampleValid = false;
        lastInaProbeMs = 0;
        return;
    }

    if (inaPresent)
        return;
    if (lastInaProbeMs != 0 && (uint32_t)(now - lastInaProbeMs) < INA226_RETRY_INTERVAL_MS)
        return;

    lastInaProbeMs = now ? now : 1;
    inaPresent = inaProbeAndConfigure();
    inaSampleValid = false;
    lastInaSampleMs = 0;
    if (!inaPresent)
        trackerDiagLog("INA226", "enabled but sensor not ready preferred=0x%02X scan=0x%02X-0x%02X retry=30s",
                       (unsigned)inaAddress, (unsigned)INA226_SCAN_FIRST, (unsigned)INA226_SCAN_LAST);
}

bool sampleIna(uint32_t now)
{
    if (!trackerIna226Enabled() || !inaPresent)
        return false;
    if (lastInaSampleMs != 0 && (uint32_t)(now - lastInaSampleMs) < INA226_SAMPLE_INTERVAL_MS)
        return inaSampleValid;

    uint16_t rawBus = 0;
    uint16_t rawCurrent = 0;
    if (!inaReadRegister(INA226_REG_BUS_VOLTAGE, rawBus) || !inaReadRegister(INA226_REG_CURRENT, rawCurrent)) {
        LOG_WARN("INA226: sample read failed addr=0x%02X; sensor marked missing and will be reprobed", (unsigned)inaAddress);
        trackerDiagLog("INA226", "sample read failed addr=0x%02X sensor marked missing and will be reprobed",
                       (unsigned)inaAddress);
        inaSampleValid = false;
        inaPresent = false;
        lastInaProbeMs = now ? now : 1;
        return false;
    }

    const uint32_t sampleDeltaMs = lastInaSampleMs == 0 ? 0U : (uint32_t)(now - lastInaSampleMs);
    lastInaSampleMs = now ? now : 1;
    inaBusVoltageMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);
    inaCurrentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;
    inaSampleValid = true;

    if (sampleDeltaMs != 0) {
        if (sampleDeltaMs <= INA226_MAX_INTEGRATION_GAP_MS) {
            if (inaCurrentUa > INA226_DISCHARGE_DEADBAND_UA) {
                inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;
                if (inaVbusIsValid(inaBusVoltageMv)) {
                    const uint64_t powerUw = ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;
                    inaEnergyUwMs += powerUw * sampleDeltaMs;
                }
            }
        } else {
            capacityWindowValid = false;
            capacityResetAfterExternal = true;
        }
    }
    return true;
}

void loadPersistentTotals()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, true))
        return;
    movingMs = (uint64_t)prefs.getULong("moveS", 0) * 1000ULL;
    parkedMs = (uint64_t)prefs.getULong("parkS", 0) * 1000ULL;
    gnssMs = (uint64_t)prefs.getULong("gpsS", 0) * 1000ULL;
    bleMs = (uint64_t)prefs.getULong("bleS", 0) * 1000ULL;
    displayMs = (uint64_t)prefs.getULong("dispS", 0) * 1000ULL;
    otherMs = (uint64_t)prefs.getULong("otherS", 0) * 1000ULL;
    positionTxCount = prefs.getULong("posTx", 0);
    dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);
    inaDischargeUaMs = (uint64_t)prefs.getULong("usedUah", 0) * 3600000ULL;
    inaEnergyUwMs = (uint64_t)prefs.getULong("usedUwh", 0) * 3600000ULL;
    inaSleepUaMs = (uint64_t)prefs.getULong("sleepUah", 0) * 3600000ULL;
    inaSleepUwMs = (uint64_t)prefs.getULong("sleepUwh", 0) * 3600000ULL;
    lightSleepMs = (uint64_t)prefs.getULong("lightSlpS", 0) * 1000ULL;
    deepSleepMs = (uint64_t)prefs.getULong("deepSlpS", 0) * 1000ULL;
    learnedCapacityMah = prefs.getULong("capMah", 0);
    capacityCycles = prefs.getUShort("capCycles", 0);
    capacityConfidence = prefs.getUChar("capConf", 0);
    prefs.end();
}

void savePersistentTotals()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putULong("moveS", clampSecs(movingMs / 1000ULL));
    prefs.putULong("parkS", clampSecs(parkedMs / 1000ULL));
    prefs.putULong("gpsS", clampSecs(gnssMs / 1000ULL));
    prefs.putULong("bleS", clampSecs(bleMs / 1000ULL));
    prefs.putULong("dispS", clampSecs(displayMs / 1000ULL));
    prefs.putULong("otherS", clampSecs(otherMs / 1000ULL));
    prefs.putULong("posTx", positionTxCount);
    prefs.putULong("rate", dischargeRateMilliPercentPerHour);
    prefs.putULong("usedUah", dischargedUah());
    prefs.putULong("usedUwh", dischargedUwh());
    prefs.putULong("sleepUah", sleepEstimatedUah());
    prefs.putULong("sleepUwh", sleepEstimatedUwh());
    prefs.putULong("lightSlpS", clampSecs(lightSleepMs / 1000ULL));
    prefs.putULong("deepSlpS", clampSecs(deepSleepMs / 1000ULL));
    prefs.putULong("capMah", learnedCapacityMah);
    prefs.putUShort("capCycles", capacityCycles);
    prefs.putUChar("capConf", capacityConfidence);
    prefs.end();
    lastPersistMeasuredSecs = measuredSecs();
}

void updateBatteryLearning(uint32_t deltaMs)
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return;
    const uint8_t percent = powerStatus->getBatteryChargePercent();
    const bool external = powerStatus->getHasUSB() || powerStatus->getIsCharging();
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
    if (percent > learningBaselinePercent + 5U) {
        resetLearning(percent);
        return;
    }

    learningMs += deltaMs;
    const uint32_t learningSecs = clampSecs(learningMs / 1000ULL);
    if (percent > learningBaselinePercent)
        return;
    const uint8_t drop = learningBaselinePercent - percent;
    if (drop == 0 || learningSecs < LEARNING_MIN_SECS)
        return;
    if (drop == lastObservedDrop && learningSecs - lastRateUpdateLearningSecs < RATE_REFRESH_SECS)
        return;

    const uint64_t observed = (uint64_t)drop * 1000ULL * 3600ULL / learningSecs;
    if (observed == 0 || observed > 100000ULL)
        return;
    const uint32_t observedRate = (uint32_t)observed;
    if (dischargeRateMilliPercentPerHour == 0)
        dischargeRateMilliPercentPerHour = observedRate;
    else
        dischargeRateMilliPercentPerHour = (dischargeRateMilliPercentPerHour * 3UL + observedRate) / 4UL;
    lastObservedDrop = drop;
    lastRateUpdateLearningSecs = learningSecs;
    if (drop >= 5U && learningSecs >= 3UL * 60UL * 60UL)
        resetLearning(percent);
}

void updateCapacityLearning()
{
    if (!trackerIna226Enabled() || !inaPresent || !inaSampleValid || !powerStatus || !powerStatus->getHasBattery())
        return;
    const uint8_t percent = powerStatus->getBatteryChargePercent();
    if (percent == 0 || percent > 100)
        return;

    const bool external =
        powerStatus->getHasUSB() || powerStatus->getIsCharging() || inaCurrentUa < -INA226_DISCHARGE_DEADBAND_UA;
    if (external) {
        capacityWindowValid = false;
        capacityResetAfterExternal = true;
        return;
    }

    const uint32_t used = totalDischargedUah();
    if (capacityResetAfterExternal || !capacityWindowValid) {
        capacityResetAfterExternal = false;
        capacityWindowValid = true;
        capacityBaselinePercent = percent;
        capacityBaselineUsedUah = used;
        return;
    }
    if (percent > capacityBaselinePercent + 5U) {
        capacityBaselinePercent = percent;
        capacityBaselineUsedUah = used;
        return;
    }
    if (percent > capacityBaselinePercent)
        return;

    const uint8_t drop = capacityBaselinePercent - percent;
    const uint32_t usedDelta = used - capacityBaselineUsedUah;
    if (drop < CAPACITY_MIN_DROP_PERCENT || usedDelta < CAPACITY_MIN_USED_UAH)
        return;

    const uint64_t estimate = (uint64_t)usedDelta * 100ULL / ((uint64_t)drop * 1000ULL);
    if (estimate < CAPACITY_MIN_MAH || estimate > CAPACITY_MAX_MAH) {
        capacityBaselinePercent = percent;
        capacityBaselineUsedUah = used;
        return;
    }

    const uint32_t estimateMah = (uint32_t)estimate;
    if (learnedCapacityMah == 0)
        learnedCapacityMah = estimateMah;
    else
        learnedCapacityMah = (learnedCapacityMah * 3UL + estimateMah + 2UL) / 4UL;
    if (capacityCycles < UINT16_MAX)
        capacityCycles++;
    const uint16_t confidence = 20U + (drop > 50U ? 50U : drop) + (capacityCycles > 2U ? 20U : (uint16_t)capacityCycles * 10U);
    capacityConfidence = confidence > 95U ? 95U : (uint8_t)confidence;

    trackerDiagLog("BATTERY_LEARN", "capacity=%umAh sample=%umAh drop=%u%% confidence=%u%% cycles=%u",
                   (unsigned)learnedCapacityMah, (unsigned)estimateMah, (unsigned)drop, (unsigned)capacityConfidence,
                   (unsigned)capacityCycles);
    capacityBaselinePercent = percent;
    capacityBaselineUsedUah = used;
    savePersistentTotals();
}

void maybeLogBattery()
{
    const uint32_t now = millis();
    if (lastBatteryLogMs != 0 && (uint32_t)(now - lastBatteryLogMs) < BATTERY_LOG_INTERVAL_MS)
        return;
    if ((!powerStatus || !powerStatus->getHasBattery()) && !trackerIna226Enabled())
        return;

    lastBatteryLogMs = now ? now : 1;
    TrackerPowerStats stats = trackerPowerMonitorStats();
    char remaining[32] = "learning";
    if (stats.estimateReady)
        trackerPowerFormatDuration(stats.remainingSecs, remaining, sizeof(remaining));
    const char *inaState = !stats.inaConfigured ? "OFF" : (!stats.inaPresent ? "MISSING" : (stats.inaValid ? "OK" : "WAIT"));
    const char *vbusState =
        !stats.inaConfigured || !stats.inaPresent ? "N/A" : (!stats.inaValid ? "WAIT" : (stats.vbusValid ? "OK" : "MISSING"));
    const int32_t c = stats.currentMilliAmpsX10;
    const int32_t ac = c < 0 ? -c : c;
    trackerDiagLog("BATTERY",
                   "%umV %u%% usb=%u charge=%u est=%s ina=%s vbus=%s current=%s%ld.%ldmA "
                   "total=%u.%umAh "
                   "sleepEst=%u.%umAh lightSleep=%us deepSleep=%us cap=%umAh conf=%u%% "
                   "move=%us park=%us gps=%us ble=%us disp=%us tx=%u",
                   (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent, stats.usbPowered ? 1U : 0U,
                   stats.charging ? 1U : 0U, remaining, inaState, vbusState, c < 0 ? "-" : "", (long)(ac / 10), (long)(ac % 10),
                   (unsigned)(stats.dischargedMahX10 / 10U), (unsigned)(stats.dischargedMahX10 % 10U),
                   (unsigned)(stats.sleepEstimatedMahX10 / 10U), (unsigned)(stats.sleepEstimatedMahX10 % 10U),
                   (unsigned)stats.lightSleepSecs, (unsigned)stats.deepSleepSecs, (unsigned)stats.learnedCapacityMah,
                   (unsigned)stats.capacityConfidence, (unsigned)stats.movingSecs, (unsigned)stats.parkedSecs,
                   (unsigned)stats.gnssSecs, (unsigned)stats.bleSecs, (unsigned)stats.displaySecs,
                   (unsigned)stats.positionTxCount);
}
} // namespace

void trackerPowerMonitorInit()
{
    if (initialized)
        return;

    loadInaAddressPreference();
    if (retainedMagic != RTC_MAGIC) {
        retainedMagic = RTC_MAGIC;
        movingMs = parkedMs = gnssMs = bleMs = displayMs = otherMs = 0;
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
        inaSleepUaMs = 0;
        inaSleepUwMs = 0;
        lightSleepMs = 0;
        deepSleepMs = 0;
        lightSleepBaselineUa = 0;
        lightSleepBaselineMv = 0;
        deepSleepLastUa = 0;
        deepSleepLastMv = 0;
        deepSleepShotPending = false;
        deepSleepPlannedSecs = 0;
        deepSleepStartEpoch = 0;
        learnedCapacityMah = 0;
        capacityCycles = 0;
        capacityConfidence = 0;
        capacityWindowValid = false;
        capacityResetAfterExternal = true;
        capacityBaselinePercent = 0;
        capacityBaselineUsedUah = 0;
        loadPersistentTotals();
    }
    initialized = true;
    recoverDeepSleepShot();
    lastTickMs = millis();
    lastPersistMeasuredSecs = measuredSecs();
}

void trackerPowerMonitorTick(bool moving, bool parked, bool gnssActive, bool bleActive, bool displayActive)
{
    if (!initialized)
        trackerPowerMonitorInit();
    const uint32_t now = millis();
    syncInaConfiguration(now);
    sampleIna(now);

    if (lastTickMs == 0) {
        lastTickMs = now;
        return;
    }
    const uint32_t deltaMs = now - lastTickMs;
    lastTickMs = now;
    if (deltaMs > 10UL * 60UL * 1000UL) {
        capacityWindowValid = false;
        capacityResetAfterExternal = true;
        return;
    }

    if (moving)
        movingMs += deltaMs;
    else if (parked)
        parkedMs += deltaMs;
    else
        otherMs += deltaMs;
    if (gnssActive)
        gnssMs += deltaMs;
    if (bleActive)
        bleMs += deltaMs;
    if (displayActive)
        displayMs += deltaMs;

    updateBatteryLearning(deltaMs);
    updateCapacityLearning();
    maybeLogBattery();
    const uint32_t total = measuredSecs();
    if (!moving && total - lastPersistMeasuredSecs >= PERSIST_INTERVAL_SECS)
        savePersistentTotals();
}

void trackerPowerMonitorNotePositionTx()
{
    if (!initialized)
        trackerPowerMonitorInit();
    positionTxCount++;
}

void trackerPowerMonitorPersist()
{
    if (!initialized)
        trackerPowerMonitorInit();
    savePersistentTotals();
}

void trackerPowerMonitorPrepareForLightSleep()
{
    if (!initialized)
        trackerPowerMonitorInit();

    const uint32_t now = millis();
    syncInaConfiguration(now);
    if (!trackerIna226Enabled() || !inaPresent)
        return;

    lightSleepStartedUs = esp_timer_get_time();
    lightSleepIntervalPending = true;

    const bool refresh = lightSleepBaselineUa <= INA226_SLEEP_MIN_UA || lastLightSleepProfileUs == 0 ||
                         lightSleepStartedUs - lastLightSleepProfileUs >= INA226_LIGHT_SLEEP_REFRESH_US;
    if (refresh && inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_SLEEP_SINGLE)) {
        lightSleepShotPending = true;
    } else {
        lightSleepShotPending = false;
        inaPowerDown();
    }

    inaSampleValid = false;
    lastInaSampleMs = 0;
}

void trackerPowerMonitorCompleteLightSleep()
{
    if (!lightSleepIntervalPending)
        return;

    const int64_t nowUs = esp_timer_get_time();
    const int64_t durationUs = nowUs > lightSleepStartedUs ? nowUs - lightSleepStartedUs : 0;
    int32_t sampleUa = lightSleepBaselineUa;
    uint16_t sampleMv = lightSleepBaselineMv;

    if (lightSleepShotPending && durationUs >= INA226_SLEEP_SHOT_MIN_US) {
        int32_t capturedUa = 0;
        uint16_t capturedMv = 0;
        if (readInaInstant(capturedUa, capturedMv)) {
            lightSleepBaselineUa = capturedUa;
            lightSleepBaselineMv = capturedMv;
            sampleUa = capturedUa;
            sampleMv = capturedMv;
            lastLightSleepProfileUs = nowUs;
            trackerDiagLog("POWER_SLEEP",
                           "role=TAK mode=light sample=%lduA %umV vbus=%s "
                           "duration=%lldms estimate=sample_x_duration",
                           (long)capturedUa, (unsigned)capturedMv, inaVbusIsValid(capturedMv) ? "OK" : "MISSING",
                           (long long)(durationUs / 1000LL));
        }
    }

    if (durationUs > 0 && sampleUa > INA226_SLEEP_MIN_UA && sampleMv != 0)
        addSleepEstimate(sampleUa, sampleMv, (uint64_t)(durationUs / 1000LL), false);

    if (trackerIna226Enabled() && inaPresent) {
        if (!inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_CONTINUOUS))
            inaPresent = false;
    }
    inaSampleValid = false;
    lastInaSampleMs = 0;
    lightSleepIntervalPending = false;
    lightSleepShotPending = false;
    lightSleepStartedUs = 0;
}

void trackerPowerMonitorPrepareForDeepSleep(uint32_t plannedSleepSecs)
{
    if (!initialized)
        trackerPowerMonitorInit();

    savePersistentTotals();
    deepSleepShotPending = false;
    deepSleepPlannedSecs = plannedSleepSecs;
    deepSleepStartEpoch = getValidTime(RTCQualityDevice);

    const uint32_t now = millis();
    syncInaConfiguration(now);
    if (trackerIna226Enabled() && inaPresent) {
        deepSleepShotPending = inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_SLEEP_SINGLE);
        if (!deepSleepShotPending)
            inaPowerDown();
    }

    inaSampleValid = false;
    lastInaSampleMs = 0;
    capacityWindowValid = false;
    capacityResetAfterExternal = true;
}

TrackerPowerStats trackerPowerMonitorStats()
{
    TrackerPowerStats out{};
    out.measuredSecs = measuredSecs();
    out.movingSecs = clampSecs(movingMs / 1000ULL);
    out.parkedSecs = clampSecs(parkedMs / 1000ULL);
    out.gnssSecs = clampSecs(gnssMs / 1000ULL);
    out.bleSecs = clampSecs(bleMs / 1000ULL);
    out.displaySecs = clampSecs(displayMs / 1000ULL);
    out.otherSecs = clampSecs(otherMs / 1000ULL);
    out.positionTxCount = positionTxCount;
    out.dischargeRateMilliPercentPerHour = dischargeRateMilliPercentPerHour;

    out.inaConfigured = trackerIna226Enabled();
    out.inaPresent = out.inaConfigured && inaPresent;
    out.inaValid = out.inaPresent && inaSampleValid;
    out.inaBusVoltageMv = inaBusVoltageMv;
    out.vbusValid = out.inaValid && inaVbusIsValid(inaBusVoltageMv);
    out.currentMilliAmpsX10 = inaCurrentUa / 100;
    if (out.inaValid && out.vbusValid) {
        const int64_t powerX10 = (int64_t)inaCurrentUa * inaBusVoltageMv / 100000LL;
        out.powerMilliWattsX10 = powerX10 > INT32_MAX ? INT32_MAX : (powerX10 < INT32_MIN ? INT32_MIN : (int32_t)powerX10);
    }
    out.awakeMeasuredMahX10 = dischargedUah() / 100U;
    out.awakeMeasuredMwhX10 = dischargedUwh() / 100U;
    out.sleepEstimatedMahX10 = sleepEstimatedUah() / 100U;
    out.sleepEstimatedMwhX10 = sleepEstimatedUwh() / 100U;
    out.dischargedMahX10 = totalDischargedUah() / 100U;
    out.dischargedMwhX10 = totalDischargedUwh() / 100U;
    out.lightSleepSecs = clampSecs(lightSleepMs / 1000ULL);
    out.deepSleepSecs = clampSecs(deepSleepMs / 1000ULL);
    out.lightSleepMilliAmpsX10 = lightSleepBaselineUa / 100;
    out.deepSleepMilliAmpsX10 = deepSleepLastUa / 100;
    out.learnedCapacityMah = learnedCapacityMah;
    out.capacityConfidence = capacityConfidence;
    out.capacityCycles = capacityCycles;
    out.capacityReady = learnedCapacityMah != 0 && capacityConfidence >= 40U;

    if (!powerStatus || !powerStatus->getHasBattery())
        return out;
    out.batteryValid = true;
    out.usbPowered = powerStatus->getHasUSB();
    out.charging = powerStatus->getIsCharging();
    const int mv = powerStatus->getBatteryVoltageMv();
    out.voltageMv = mv > 0 && mv < 65536 ? (uint16_t)mv : 0;
    out.batteryPercent = powerStatus->getBatteryChargePercent();
    if (out.capacityReady && out.batteryPercent <= 100)
        out.remainingCapacityMah = ((uint64_t)out.learnedCapacityMah * out.batteryPercent + 50ULL) / 100ULL;
    if (!out.usbPowered && !out.charging && out.batteryPercent > 0 && out.batteryPercent <= 100 &&
        dischargeRateMilliPercentPerHour > 0) {
        const uint64_t remaining = (uint64_t)out.batteryPercent * 1000ULL * 3600ULL / dischargeRateMilliPercentPerHour;
        out.remainingSecs = clampSecs(remaining);
        out.estimateReady = true;
    }
    return out;
}

void trackerPowerFormatDuration(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint32_t days = seconds / 86400UL;
    const uint32_t hours = (seconds % 86400UL) / 3600UL;
    const uint32_t mins = (seconds % 3600UL) / 60UL;
    snprintf(out, outSize, "%ud %02uh %02umin", (unsigned)days, (unsigned)hours, (unsigned)mins);
}

#endif
