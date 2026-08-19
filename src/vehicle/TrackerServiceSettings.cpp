#include "TrackerServiceSettings.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(ARCH_ESP32)

#include "configuration.h"
#include "modules/PositionModule.h"

#include <Preferences.h>

namespace {
constexpr const char *PREF_NAMESPACE = "trkV11";

// Presets are intentionally small and conservative. Index 2 is the current
// field-tested baseline: 3 falling edges within 3 seconds.
struct MotionPreset {
    const char *name;
    uint8_t count;
    uint32_t windowMs;
};

constexpr MotionPreset MOTION_PRESETS[] = {
    {"VERY SENS", 2, 3000},
    {"SENSITIVE", 3, 4000},
    {"NORMAL", 3, 3000},
    {"ROBUST", 4, 3000},
};

constexpr uint16_t DISTANCE_PRESETS[] = {50, 75, 100, 150};
constexpr uint16_t INTERVAL_PRESETS[] = {30, 45, 60, 90};
constexpr uint16_t PARK_PRESETS[] = {30, 60, 120, 240};

uint8_t motionIndex = 2;
uint8_t distanceIndex = 1;
uint8_t intervalIndex = 0;
uint8_t parkIndex = 1;
bool initialized = false;

template <typename T, size_t N> uint8_t sanitizeIndex(uint8_t index, const T (&)[N], uint8_t fallback)
{
    return index < N ? index : fallback;
}

void saveByte(const char *key, uint8_t value)
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putUChar(key, value);
    prefs.end();
}
} // namespace

void trackerServiceSettingsInit()
{
    if (initialized)
        return;

    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        motionIndex = sanitizeIndex(prefs.getUChar("motion", 2), MOTION_PRESETS, 2);
        distanceIndex = sanitizeIndex(prefs.getUChar("distance", 1), DISTANCE_PRESETS, 1);
        intervalIndex = sanitizeIndex(prefs.getUChar("interval", 0), INTERVAL_PRESETS, 0);
        parkIndex = sanitizeIndex(prefs.getUChar("park", 1), PARK_PRESETS, 1);
        prefs.end();
    }

    initialized = true;
    trackerApplyPositionSettings();

    LOG_INFO("Tracker V1.1 settings: motion=%s (%u/%ums) distance=%um interval=%us park=%umin",
             trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
             (unsigned)trackerMotionConfirmWindowMs(), (unsigned)trackerSmartDistanceM(),
             (unsigned)trackerSmartIntervalSecs(), (unsigned)trackerParkIntervalMinutes());
}

void trackerApplyPositionSettings()
{
    config.position.position_broadcast_smart_enabled = true;
    config.position.broadcast_smart_minimum_distance = trackerSmartDistanceM();
    config.position.broadcast_smart_minimum_interval_secs = trackerSmartIntervalSecs();
    config.position.position_broadcast_secs = trackerParkIntervalSecs();

    // PositionModule used to cache this value only at construction. The tracker
    // branch exposes a refresh method so a service-menu change takes effect now,
    // without requiring a reboot.
    if (positionModule)
        positionModule->refreshSmartPositionMinimumInterval();
}

uint8_t trackerMotionSensitivityIndex()
{
    return motionIndex;
}

const char *trackerMotionSensitivityName()
{
    return MOTION_PRESETS[motionIndex].name;
}

uint8_t trackerMotionConfirmCount()
{
    return MOTION_PRESETS[motionIndex].count;
}

uint32_t trackerMotionConfirmWindowMs()
{
    return MOTION_PRESETS[motionIndex].windowMs;
}

uint16_t trackerSmartDistanceM()
{
    return DISTANCE_PRESETS[distanceIndex];
}

uint16_t trackerSmartIntervalSecs()
{
    return INTERVAL_PRESETS[intervalIndex];
}

uint16_t trackerParkIntervalMinutes()
{
    return PARK_PRESETS[parkIndex];
}

uint32_t trackerParkIntervalSecs()
{
    return (uint32_t)trackerParkIntervalMinutes() * 60UL;
}

void trackerCycleMotionSensitivity()
{
    motionIndex = (uint8_t)((motionIndex + 1U) % (sizeof(MOTION_PRESETS) / sizeof(MOTION_PRESETS[0])));
    saveByte("motion", motionIndex);
    LOG_INFO("Tracker V1.1 setting changed: motion=%s (%u/%ums)", trackerMotionSensitivityName(),
             (unsigned)trackerMotionConfirmCount(), (unsigned)trackerMotionConfirmWindowMs());
}

void trackerCycleSmartDistance()
{
    distanceIndex = (uint8_t)((distanceIndex + 1U) % (sizeof(DISTANCE_PRESETS) / sizeof(DISTANCE_PRESETS[0])));
    saveByte("distance", distanceIndex);
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: smart distance=%um", (unsigned)trackerSmartDistanceM());
}

void trackerCycleSmartInterval()
{
    intervalIndex = (uint8_t)((intervalIndex + 1U) % (sizeof(INTERVAL_PRESETS) / sizeof(INTERVAL_PRESETS[0])));
    saveByte("interval", intervalIndex);
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: smart interval=%us", (unsigned)trackerSmartIntervalSecs());
}

void trackerCycleParkInterval()
{
    parkIndex = (uint8_t)((parkIndex + 1U) % (sizeof(PARK_PRESETS) / sizeof(PARK_PRESETS[0])));
    saveByte("park", parkIndex);
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: park interval=%umin", (unsigned)trackerParkIntervalMinutes());
}

#endif // HELTEC_TRACKER_V1_1 && ARCH_ESP32
