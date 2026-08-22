#include "infrastructure/HeltecV3PowerMonitor.h"

#if defined(_VARIANT_HELTEC_V3)

#include "PowerStatus.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"

#include <Arduino.h>
#include <Preferences.h>
#include <esp_attr.h>
#include <cstdio>

namespace
{
constexpr uint32_t RTC_MAGIC = 0x56335057U; // V3PW
constexpr const char *PREF_NAMESPACE = "v3Power";
constexpr uint32_t BATTERY_LOG_INTERVAL_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t PERSIST_INTERVAL_SECS = 6UL * 60UL * 60UL;
constexpr uint32_t LEARNING_MIN_SECS = 60UL * 60UL;
constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;

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

bool initialized = false;
uint32_t lastTickMs = 0;
uint32_t lastBatteryLogMs = 0;
uint32_t lastPersistMeasuredSecs = 0;

uint32_t clampSecs(uint64_t value)
{
    return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

uint32_t measuredSecs()
{
    return clampSecs((listenMs + serviceMs) / 1000ULL);
}

void resetLearning(uint8_t percent)
{
    learningValid = percent > 0 && percent <= 100;
    learningBaselinePercent = learningValid ? percent : 0;
    learningMs = 0;
    lastObservedDrop = 0;
    lastRateUpdateLearningSecs = 0;
}

void loadPersistentTotals()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, true))
        return;

    listenMs = (uint64_t)prefs.getULong("listenS", 0) * 1000ULL;
    serviceMs = (uint64_t)prefs.getULong("serviceS", 0) * 1000ULL;
    bleMs = (uint64_t)prefs.getULong("bleS", 0) * 1000ULL;
    displayMs = (uint64_t)prefs.getULong("dispS", 0) * 1000ULL;
    positionTxCount = prefs.getULong("posTx", 0);
    dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);
    prefs.end();
}

void savePersistentTotals()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;

    prefs.putULong("listenS", clampSecs(listenMs / 1000ULL));
    prefs.putULong("serviceS", clampSecs(serviceMs / 1000ULL));
    prefs.putULong("bleS", clampSecs(bleMs / 1000ULL));
    prefs.putULong("dispS", clampSecs(displayMs / 1000ULL));
    prefs.putULong("posTx", positionTxCount);
    prefs.putULong("rate", dischargeRateMilliPercentPerHour);
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

    if (drop == lastObservedDrop && learningSecs - lastRateUpdateLearningSecs < RATE_REFRESH_SECS)
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

void maybeLogBattery()
{
    const uint32_t now = millis();
    if (lastBatteryLogMs != 0 && (uint32_t)(now - lastBatteryLogMs) < BATTERY_LOG_INTERVAL_MS)
        return;
    if (!powerStatus || !powerStatus->getHasBattery())
        return;

    lastBatteryLogMs = now ? now : 1;
    const HeltecV3PowerStats stats = heltecV3PowerMonitorStats();
    char remaining[32] = "learning";
    if (stats.estimateReady)
        heltecV3PowerFormatDuration(stats.remainingSecs, remaining, sizeof(remaining));

    heltecV3DiagLog("BATTERY", "src=internal %umV %u%% usb=%u charge=%u est=%s listen=%us service=%us ble=%us disp=%us tx=%u",
                    (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent, stats.usbPowered ? 1U : 0U,
                    stats.charging ? 1U : 0U, remaining, (unsigned)stats.listenSecs, (unsigned)stats.serviceSecs,
                    (unsigned)stats.bleSecs, (unsigned)stats.displaySecs, (unsigned)stats.positionTxCount);
}
} // namespace

void heltecV3PowerMonitorInit()
{
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
        loadPersistentTotals();
    }

    initialized = true;
    lastTickMs = millis();
    lastPersistMeasuredSecs = measuredSecs();
    heltecV3DiagLog("POWER", "monitor initialized source=internal ina226=prepared-not-enabled");
}

void heltecV3PowerMonitorTick(bool listening, bool serviceActive, bool bleActive, bool displayActive)
{
    if (!initialized)
        heltecV3PowerMonitorInit();

    const uint32_t now = millis();
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

    updateBatteryLearning(deltaMs);
    maybeLogBattery();

    const uint32_t total = measuredSecs();
    if (!serviceActive && total - lastPersistMeasuredSecs >= PERSIST_INTERVAL_SECS)
        savePersistentTotals();
}

void heltecV3PowerMonitorNotePositionTx()
{
    if (!initialized)
        heltecV3PowerMonitorInit();
    positionTxCount++;
}

void heltecV3PowerMonitorPersist()
{
    if (!initialized)
        heltecV3PowerMonitorInit();
    savePersistentTotals();
}

HeltecV3PowerStats heltecV3PowerMonitorStats()
{
    HeltecV3PowerStats out{};
    out.source = HeltecV3PowerSource::INTERNAL;
    out.measuredSecs = measuredSecs();
    out.listenSecs = clampSecs(listenMs / 1000ULL);
    out.serviceSecs = clampSecs(serviceMs / 1000ULL);
    out.bleSecs = clampSecs(bleMs / 1000ULL);
    out.displaySecs = clampSecs(displayMs / 1000ULL);
    out.positionTxCount = positionTxCount;
    out.dischargeRateMilliPercentPerHour = dischargeRateMilliPercentPerHour;

    // INA226-facing values deliberately stay invalid here. When the sensor is
    // installed later, only the source backend needs to populate these fields.
    out.currentValid = false;
    out.energyValid = false;

    if (!powerStatus || !powerStatus->getHasBattery())
        return out;

    out.batteryValid = true;
    out.usbPowered = powerStatus->getHasUSB();
    out.charging = powerStatus->getIsCharging();
    const int mv = powerStatus->getBatteryVoltageMv();
    out.voltageMv = mv > 0 && mv < 65536 ? (uint16_t)mv : 0;
    out.batteryPercent = powerStatus->getBatteryChargePercent();

    if (!out.usbPowered && !out.charging && out.batteryPercent > 0 && out.batteryPercent <= 100 &&
        dischargeRateMilliPercentPerHour > 0) {
        const uint64_t remaining =
            (uint64_t)out.batteryPercent * 1000ULL * 3600ULL / dischargeRateMilliPercentPerHour;
        out.remainingSecs = clampSecs(remaining);
        out.estimateReady = true;
    }
    return out;
}

const char *heltecV3PowerMonitorSourceText()
{
    return "INTERNAL";
}

void heltecV3PowerFormatDuration(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;

    const uint32_t days = seconds / 86400UL;
    const uint32_t hours = (seconds % 86400UL) / 3600UL;
    const uint32_t mins = (seconds % 3600UL) / 60UL;
    snprintf(out, outSize, "%ud %02uh %02umin", (unsigned)days, (unsigned)hours, (unsigned)mins);
}

#endif
