#include "vehicle/TrackerPowerMonitor.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "PowerStatus.h"
#include "vehicle/TrackerDiagnosticLog.h"

#include <Arduino.h>
#include <Preferences.h>
#include <esp_attr.h>
#include <cstdio>

namespace
{
constexpr uint32_t RTC_MAGIC = 0x54525057U; // TRPW
constexpr const char *PREF_NAMESPACE = "trkPower";
constexpr uint32_t BATTERY_LOG_INTERVAL_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t PERSIST_INTERVAL_SECS = 6UL * 60UL * 60UL;
constexpr uint32_t LEARNING_MIN_SECS = 60UL * 60UL;
constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;

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
    return clampSecs((movingMs + parkedMs + otherMs) / 1000ULL);
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

    movingMs = (uint64_t)prefs.getULong("moveS", 0) * 1000ULL;
    parkedMs = (uint64_t)prefs.getULong("parkS", 0) * 1000ULL;
    gnssMs = (uint64_t)prefs.getULong("gpsS", 0) * 1000ULL;
    bleMs = (uint64_t)prefs.getULong("bleS", 0) * 1000ULL;
    displayMs = (uint64_t)prefs.getULong("dispS", 0) * 1000ULL;
    otherMs = (uint64_t)prefs.getULong("otherS", 0) * 1000ULL;
    positionTxCount = prefs.getULong("posTx", 0);
    dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);
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

    // A large upward jump without an observed USB phase normally means the
    // battery was changed or charged while the node was off. Start a new window.
    if (percent > learningBaselinePercent + 5U) {
        resetLearning(percent);
        return;
    }

    learningMs += deltaMs;
    const uint32_t learningSecs = clampSecs(learningMs / 1000ULL);
    if (percent > learningBaselinePercent)
        return; // small Li-ion voltage rebound; keep the long-term baseline.

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

    // Rebase periodically so the estimator follows a changed duty cycle rather
    // than averaging the entire lifetime of the battery forever.
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
    TrackerPowerStats stats = trackerPowerMonitorStats();
    char remaining[32] = "learning";
    if (stats.estimateReady)
        trackerPowerFormatDuration(stats.remainingSecs, remaining, sizeof(remaining));

    trackerDiagLog("BATTERY", "%umV %u%% usb=%u charge=%u est=%s move=%us park=%us gps=%us ble=%us disp=%us tx=%u",
                   (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent, stats.usbPowered ? 1U : 0U,
                   stats.charging ? 1U : 0U, remaining, (unsigned)stats.movingSecs, (unsigned)stats.parkedSecs,
                   (unsigned)stats.gnssSecs, (unsigned)stats.bleSecs, (unsigned)stats.displaySecs,
                   (unsigned)stats.positionTxCount);
}
} // namespace

void trackerPowerMonitorInit()
{
    if (initialized)
        return;

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
        loadPersistentTotals();
    }

    initialized = true;
    lastTickMs = millis();
    lastPersistMeasuredSecs = measuredSecs();
}

void trackerPowerMonitorTick(bool moving, bool parked, bool gnssActive, bool bleActive, bool displayActive)
{
    if (!initialized)
        trackerPowerMonitorInit();

    const uint32_t now = millis();
    if (lastTickMs == 0) {
        lastTickMs = now;
        return;
    }

    const uint32_t deltaMs = now - lastTickMs;
    lastTickMs = now;
    if (deltaMs > 10UL * 60UL * 1000UL)
        return; // do not attribute an unexplained long reset/power-off gap.

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
