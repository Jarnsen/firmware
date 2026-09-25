#include "jarnsen/core/power/JarnsenBatteryLearning.h"

#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)

#include "PowerStatus.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"

#include <Arduino.h>
#include <Preferences.h>
#include <cstdio>
#include <esp_attr.h>

namespace jarnsen
{
namespace
{

// Keep the SOC/time learner deliberately aligned with TrackerPowerMonitor:
// one hour minimum observation, refresh at most every 30 minutes for the same
// percentage drop, and start a fresh window after a useful 5%/3h sample.
constexpr uint32_t RTC_MAGIC = 0x4A563342U; // "JV3B"
constexpr const char *PREF_NAMESPACE = "jrnV3Battery";
constexpr uint32_t LEARNING_MIN_SECS = 60UL * 60UL;
constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;
constexpr uint32_t MAX_TICK_GAP_MS = 10UL * 60UL * 1000UL;

RTC_DATA_ATTR uint32_t retainedMagic = 0;
RTC_DATA_ATTR bool learningValid = false;
RTC_DATA_ATTR bool baselineResetAfterExternal = true;
RTC_DATA_ATTR uint8_t learningBaselinePercent = 0;
RTC_DATA_ATTR uint64_t learningMs = 0;
RTC_DATA_ATTR uint8_t lastObservedDrop = 0;
RTC_DATA_ATTR uint32_t lastRateUpdateLearningSecs = 0;
RTC_DATA_ATTR uint64_t measuredMs = 0;

bool initialized = false;
uint32_t lastTickMs = 0;
uint32_t dischargeRateMilliPercentPerHour = 0;
uint16_t observations = 0;

uint32_t clamp32(uint64_t value)
{
    return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

void resetLearning(uint8_t percent)
{
    learningValid = percent > 0 && percent <= 100;
    learningBaselinePercent = learningValid ? percent : 0;
    learningMs = 0;
    lastObservedDrop = 0;
    lastRateUpdateLearningSecs = 0;
}

void loadPersistent()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, true))
        return;
    dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);
    observations = prefs.getUShort("obs", 0);
    prefs.end();
}

void savePersistent()
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putULong("rate", dischargeRateMilliPercentPerHour);
    prefs.putUShort("obs", observations);
    prefs.end();
}

void updateLearning(uint32_t deltaMs)
{
    if (!powerStatus || !powerStatus->isInitialized() || !powerStatus->getHasBattery())
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

    // Treat a significant upward jump as a new battery/charge state instead of
    // teaching the learner a false low discharge rate.
    if (percent > learningBaselinePercent + 5U) {
        resetLearning(percent);
        return;
    }

    learningMs += deltaMs;
    measuredMs += deltaMs;
    const uint32_t learningSecs = clamp32(learningMs / 1000ULL);

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

    if (observations < UINT16_MAX)
        ++observations;
    lastObservedDrop = drop;
    lastRateUpdateLearningSecs = learningSecs;
    savePersistent();

    BatteryLearningStats stats = batteryLearningStats();
    diagnosticLog("BATTERY_LEARN",
                  "board=HELTEC_V3 source=soc_time rate=%u.%03u%%/h drop=%u%% elapsed=%us observations=%u remaining=%us "
                  "ina226=off current=unsupported capacity_mah=unsupported",
                  (unsigned)(dischargeRateMilliPercentPerHour / 1000U),
                  (unsigned)(dischargeRateMilliPercentPerHour % 1000U), (unsigned)drop, (unsigned)learningSecs,
                  (unsigned)observations, stats.estimateReady ? (unsigned)stats.remainingSecs : 0U);

    if (drop >= 5U && learningSecs >= 3UL * 60UL * 60UL)
        resetLearning(percent);
}

} // namespace

void batteryLearningInit()
{
    if (initialized)
        return;

    loadPersistent();
    if (retainedMagic != RTC_MAGIC) {
        retainedMagic = RTC_MAGIC;
        learningValid = false;
        baselineResetAfterExternal = true;
        learningBaselinePercent = 0;
        learningMs = 0;
        lastObservedDrop = 0;
        lastRateUpdateLearningSecs = 0;
        measuredMs = 0;
    }

    initialized = true;
    lastTickMs = millis();
    diagnosticLog("BATTERY_LEARN", "board=HELTEC_V3 mode=soc_time persisted_rate=%u.%03u%%/h observations=%u ina226=off",
                  (unsigned)(dischargeRateMilliPercentPerHour / 1000U),
                  (unsigned)(dischargeRateMilliPercentPerHour % 1000U), (unsigned)observations);
}

void batteryLearningTick()
{
    if (!initialized)
        batteryLearningInit();

    const uint32_t now = millis();
    if (lastTickMs == 0) {
        lastTickMs = now;
        return;
    }

    const uint32_t deltaMs = now - lastTickMs;
    lastTickMs = now;
    if (deltaMs > MAX_TICK_GAP_MS) {
        baselineResetAfterExternal = true;
        return;
    }

    updateLearning(deltaMs);
}

void batteryLearningPersist()
{
    if (!initialized)
        batteryLearningInit();
    savePersistent();
}

BatteryLearningStats batteryLearningStats()
{
    BatteryLearningStats out{};
    out.supported = true;
    out.dischargeRateMilliPercentPerHour = dischargeRateMilliPercentPerHour;
    out.measuredSecs = clamp32(measuredMs / 1000ULL);
    out.observations = observations;

    if (!powerStatus || !powerStatus->isInitialized() || !powerStatus->getHasBattery())
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
        out.remainingSecs = clamp32(remaining);
        out.estimateReady = true;
    }
    return out;
}

void batteryLearningFormatDuration(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint32_t days = seconds / 86400UL;
    const uint32_t hours = (seconds % 86400UL) / 3600UL;
    const uint32_t mins = (seconds % 3600UL) / 60UL;
    snprintf(out, outSize, "%ud %02uh %02umin", (unsigned)days, (unsigned)hours, (unsigned)mins);
}

void batteryLearningFormatCompactDuration(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint32_t days = seconds / 86400UL;
    const uint32_t hours = (seconds % 86400UL) / 3600UL;
    const uint32_t mins = (seconds % 3600UL) / 60UL;
    if (days)
        snprintf(out, outSize, "%ud%02uh", (unsigned)days, (unsigned)hours);
    else if (hours)
        snprintf(out, outSize, "%uh%02um", (unsigned)hours, (unsigned)mins);
    else
        snprintf(out, outSize, "%umin", (unsigned)mins);
}

} // namespace jarnsen

#else

namespace jarnsen
{

void batteryLearningInit() {}
void batteryLearningTick() {}
void batteryLearningPersist() {}
BatteryLearningStats batteryLearningStats()
{
    return {};
}
void batteryLearningFormatDuration(uint32_t, char *out, size_t outSize)
{
    if (out && outSize)
        out[0] = '\0';
}
void batteryLearningFormatCompactDuration(uint32_t, char *out, size_t outSize)
{
    if (out && outSize)
        out[0] = '\0';
}

} // namespace jarnsen

#endif
