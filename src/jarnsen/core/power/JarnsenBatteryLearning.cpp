#include "jarnsen/core/power/JarnsenBatteryLearning.h"

#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || \
    defined(SEEED_WIO_TRACKER_L1) || defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)

#include "FSCommon.h"
#include "PowerStatus.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"

#include <Arduino.h>
#include <cstdio>

namespace jarnsen
{
namespace
{

// Keep this deliberately aligned with TrackerPowerMonitor:
// - at least one hour of observation,
// - no more than one refresh per 30 minutes for an unchanged SOC drop,
// - 3:1 smoothing between the established and new observed rate,
// - restart a useful learning window after >=5% over >=3h.
constexpr uint32_t LEARNING_MIN_SECS = 60UL * 60UL;
constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;
constexpr uint32_t MAX_TICK_GAP_MS = 10UL * 60UL * 1000UL;

constexpr const char *PERSIST_PATH = "/prefs/jarnsen-battery-learning-v1";
constexpr uint32_t PERSIST_MAGIC = 0x4A424C31U; // "JBL1"
constexpr uint8_t PERSIST_VERSION = 1U;

struct PersistRecord {
    uint32_t magic;
    uint8_t version;
    uint8_t reserved;
    uint16_t observations;
    uint32_t dischargeRateMilliPercentPerHour;
    uint32_t checksum;
};

bool initialized = false;
bool learningValid = false;
bool baselineResetAfterExternal = true;
uint8_t learningBaselinePercent = 0;
uint64_t learningMs = 0;
uint8_t lastObservedDrop = 0;
uint32_t lastRateUpdateLearningSecs = 0;
uint64_t measuredMs = 0;

uint32_t lastTickMs = 0;
uint32_t dischargeRateMilliPercentPerHour = 0;
uint16_t observations = 0;

uint32_t clamp32(uint64_t value)
{
    return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

uint32_t recordChecksum(const PersistRecord &record)
{
    return record.magic ^ ((uint32_t)record.version << 24) ^ ((uint32_t)record.observations << 8) ^
           record.dischargeRateMilliPercentPerHour ^ 0xA57B31C2U;
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
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(PERSIST_PATH, FILE_O_READ);
    if (!file)
        return;

    PersistRecord record{};
    const size_t got = file.read(reinterpret_cast<uint8_t *>(&record), sizeof(record));
    file.close();
    if (got != sizeof(record) || record.magic != PERSIST_MAGIC || record.version != PERSIST_VERSION ||
        record.checksum != recordChecksum(record))
        return;

    // A realistic learned rate is >0 and <=100%/h (100000 milli-%/h).
    if (record.dischargeRateMilliPercentPerHour > 100000UL)
        return;

    dischargeRateMilliPercentPerHour = record.dischargeRateMilliPercentPerHour;
    observations = record.observations;
#endif
}

void savePersistent()
{
#ifdef FSCom
    PersistRecord record{};
    record.magic = PERSIST_MAGIC;
    record.version = PERSIST_VERSION;
    record.observations = observations;
    record.dischargeRateMilliPercentPerHour = dischargeRateMilliPercentPerHour;
    record.checksum = recordChecksum(record);

    concurrency::LockGuard guard(spiLock);
    if (FSCom.exists(PERSIST_PATH))
        FSCom.remove(PERSIST_PATH);
    File file = FSCom.open(PERSIST_PATH, FILE_O_WRITE);
    if (!file)
        return;
    file.write(reinterpret_cast<const uint8_t *>(&record), sizeof(record));
    file.flush();
    file.close();
#endif
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

    // A significant upward jump means charging/battery replacement or SOC
    // correction. Start a fresh window rather than teaching a false slow rate.
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

    const BatteryLearningStats stats = batteryLearningStats();
    diagnosticLog("BATTERY_LEARN",
                  "board=%s source=soc_time rate=%u.%03u%%/h drop=%u%% elapsed=%us observations=%u remaining=%us "
                  "ina226=off current=unsupported capacity_mah=unsupported",
                  build::hardwareName, (unsigned)(dischargeRateMilliPercentPerHour / 1000U),
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
    learningValid = false;
    baselineResetAfterExternal = true;
    learningBaselinePercent = 0;
    learningMs = 0;
    lastObservedDrop = 0;
    lastRateUpdateLearningSecs = 0;
    measuredMs = 0;

    initialized = true;
    lastTickMs = millis();
    diagnosticLog("BATTERY_LEARN",
                  "board=%s mode=soc_time persisted_rate=%u.%03u%%/h observations=%u ina226=off "
                  "current=unsupported capacity_mah=unsupported",
                  build::hardwareName, (unsigned)(dischargeRateMilliPercentPerHour / 1000U),
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
