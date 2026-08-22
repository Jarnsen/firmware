#include "TrackerServiceSettings.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "configuration.h"
#include "modules/PositionModule.h"

#include <Preferences.h>
#include <cstdio>

namespace {
constexpr const char *PREF_NAMESPACE = "trkV11";

struct MotionPreset {
    const char *name;
    uint8_t count;
    uint32_t windowMs;
};

constexpr MotionPreset MOTION_PRESETS[] = {
    {"VERY SENS", 1, 3000},
    {"SENSITIVE", 2, 4000},
    {"NORMAL", 2, 3000},
    {"ROBUST", 3, 3000},
};

constexpr uint16_t DISTANCE_PRESETS[] = {50, 75, 100, 150};
constexpr uint16_t INTERVAL_PRESETS[] = {30, 45, 60, 90};
constexpr uint16_t MOVING_GNSS_PRESETS[] = {5, 10, 15, 30};
constexpr uint16_t PARK_GPS_SEARCH_PRESETS[] = {15, 30, 45, 60};
constexpr uint16_t BLE_IDLE_PRESETS[] = {60, 120, 180, 300};
constexpr uint16_t BLE_HARD_PRESETS[] = {300, 600, 900, 1800};
constexpr uint16_t PARK_PRESETS[] = {20, 30, 60, 120, 240, 360, 540, 720};
constexpr uint16_t LEGACY_PARK_PRESETS[] = {30, 60, 120, 240};

uint8_t motionIndex = 2;
uint8_t distanceIndex = 1;
uint8_t intervalIndex = 0;
uint8_t movingGnssIndex = 1;     // 10 s default
uint8_t parkGpsSearchIndex = 1;  // 30 s default
uint8_t bleIdleIndex = 1;        // 120 s default
uint8_t bleHardIndex = 2;        // 15 min default
uint8_t parkIndex = 2;           // 60 min
bool initialized = false;

template <typename T, size_t N> uint8_t sanitizeIndex(uint8_t index, const T (&)[N], uint8_t fallback)
{
    return index < N ? index : fallback;
}

template <size_t N> uint8_t findValueIndex(uint16_t value, const uint16_t (&values)[N], uint8_t fallback)
{
    for (uint8_t i = 0; i < N; ++i) {
        if (values[i] == value)
            return i;
    }
    return fallback;
}

void saveByte(const char *key, uint8_t value)
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putUChar(key, value);
    prefs.end();
}

void saveUShort(const char *key, uint16_t value)
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putUShort(key, value);
    prefs.end();
}

void saveParkMinutes(uint16_t minutes)
{
    Preferences prefs;
    if (!prefs.begin(PREF_NAMESPACE, false))
        return;
    prefs.putUShort("parkMin", minutes);
    prefs.putUChar("park", parkIndex); // keep a compatible index for diagnostics/fallback
    prefs.end();
}

uint32_t trackerNodeHash()
{
    if (!nodeDB)
        return 0;

    uint32_t x = nodeDB->getNodeNum();
    x ^= x >> 16;
    x *= 0x7feb352dU;
    x ^= x >> 15;
    x *= 0x846ca68bU;
    x ^= x >> 16;
    return x;
}
} // namespace

void trackerServiceSettingsInit()
{
    if (initialized)
        return;

    bool migratePark = false;
    uint16_t migratedParkMinutes = 60;
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        motionIndex = sanitizeIndex(prefs.getUChar("motion", 2), MOTION_PRESETS, 2);
        distanceIndex = sanitizeIndex(prefs.getUChar("distance", 1), DISTANCE_PRESETS, 1);
        intervalIndex = sanitizeIndex(prefs.getUChar("interval", 0), INTERVAL_PRESETS, 0);

        movingGnssIndex = findValueIndex(prefs.getUShort("moveGps", 10), MOVING_GNSS_PRESETS, 1);
        parkGpsSearchIndex = findValueIndex(prefs.getUShort("gpsWait", 30), PARK_GPS_SEARCH_PRESETS, 1);
        bleIdleIndex = findValueIndex(prefs.getUShort("bleIdle", 120), BLE_IDLE_PRESETS, 1);
        bleHardIndex = findValueIndex(prefs.getUShort("bleHard", 900), BLE_HARD_PRESETS, 2);

        const uint16_t savedMinutes = prefs.getUShort("parkMin", 0);
        if (savedMinutes != 0) {
            parkIndex = findValueIndex(savedMinutes, PARK_PRESETS, 2);
        } else {
            const uint8_t oldIndex = sanitizeIndex(prefs.getUChar("park", 1), LEGACY_PARK_PRESETS, 1);
            migratedParkMinutes = LEGACY_PARK_PRESETS[oldIndex];
            parkIndex = findValueIndex(migratedParkMinutes, PARK_PRESETS, 2);
            migratePark = true;
        }
        prefs.end();
    }

    initialized = true;
    if (migratePark)
        saveParkMinutes(migratedParkMinutes);
    trackerApplyPositionSettings();

    LOG_INFO("Tracker V1.1 settings: motion=%s (%u/%ums) distance=%um interval=%us movingGNSS=%us parkGPS=%us "
             "BLEidle=%us BLEhard=%us park=%umin effective=%us",
             trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
             (unsigned)trackerMotionConfirmWindowMs(), (unsigned)trackerSmartDistanceM(),
             (unsigned)trackerSmartIntervalSecs(), (unsigned)trackerMovingGnssSecs(),
             (unsigned)trackerParkGpsSearchSecs(), (unsigned)trackerBleIdleTimeoutSecs(),
             (unsigned)trackerBleHardTimeoutSecs(), (unsigned)trackerParkIntervalMinutes(),
             (unsigned)trackerEffectiveParkIntervalSecs());
}

void trackerApplyPositionSettings()
{
    config.position.position_broadcast_smart_enabled = true;
    config.position.broadcast_smart_minimum_distance = trackerSmartDistanceM();
    config.position.broadcast_smart_minimum_interval_secs = trackerSmartIntervalSecs();
    config.position.position_broadcast_secs = trackerEffectiveParkIntervalSecs();

    // The TAK light-sleep timer must follow a changed park interval immediately.
    config.power.ls_secs = trackerEffectiveParkIntervalSecs();

    if (positionModule)
        positionModule->refreshSmartPositionMinimumInterval();
}

uint8_t trackerMotionSensitivityIndex() { return motionIndex; }
const char *trackerMotionSensitivityName() { return MOTION_PRESETS[motionIndex].name; }
uint8_t trackerMotionConfirmCount() { return MOTION_PRESETS[motionIndex].count; }
uint32_t trackerMotionConfirmWindowMs() { return MOTION_PRESETS[motionIndex].windowMs; }
uint16_t trackerSmartDistanceM() { return DISTANCE_PRESETS[distanceIndex]; }
uint16_t trackerSmartIntervalSecs() { return INTERVAL_PRESETS[intervalIndex]; }
uint16_t trackerMovingGnssSecs() { return MOVING_GNSS_PRESETS[movingGnssIndex]; }
uint16_t trackerParkGpsSearchSecs() { return PARK_GPS_SEARCH_PRESETS[parkGpsSearchIndex]; }
uint16_t trackerBleIdleTimeoutSecs() { return BLE_IDLE_PRESETS[bleIdleIndex]; }
uint16_t trackerBleHardTimeoutSecs() { return BLE_HARD_PRESETS[bleHardIndex]; }
uint16_t trackerParkIntervalMinutes() { return PARK_PRESETS[parkIndex]; }
uint32_t trackerParkIntervalSecs() { return (uint32_t)trackerParkIntervalMinutes() * 60UL; }

uint32_t trackerEffectiveParkIntervalSecs()
{
    const uint32_t base = trackerParkIntervalSecs();
    if (base < 3600UL || !nodeDB)
        return base;

    const uint32_t jitterSecs = trackerNodeHash() % 181U;
    return base > jitterSecs ? base - jitterSecs : base;
}

void trackerFormatParkInterval(char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return;
    const uint16_t minutes = trackerParkIntervalMinutes();
    if (minutes >= 120 && (minutes % 60U) == 0)
        snprintf(out, outSize, "%u h", (unsigned)(minutes / 60U));
    else
        snprintf(out, outSize, "%u min", (unsigned)minutes);
}

bool trackerSetMotionSensitivityIndex(uint8_t index)
{
    if (index >= sizeof(MOTION_PRESETS) / sizeof(MOTION_PRESETS[0]))
        return false;
    motionIndex = index;
    saveByte("motion", motionIndex);
    LOG_INFO("Tracker V1.1 setting changed: motion=%s (%u/%ums)", trackerMotionSensitivityName(),
             (unsigned)trackerMotionConfirmCount(), (unsigned)trackerMotionConfirmWindowMs());
    return true;
}

bool trackerSetSmartDistanceM(uint16_t meters)
{
    const uint8_t index = findValueIndex(meters, DISTANCE_PRESETS, 255);
    if (index == 255)
        return false;
    distanceIndex = index;
    saveByte("distance", distanceIndex);
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: smart distance=%um", (unsigned)trackerSmartDistanceM());
    return true;
}

bool trackerSetSmartIntervalSecs(uint16_t seconds)
{
    const uint8_t index = findValueIndex(seconds, INTERVAL_PRESETS, 255);
    if (index == 255)
        return false;
    intervalIndex = index;
    saveByte("interval", intervalIndex);
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: smart interval=%us", (unsigned)trackerSmartIntervalSecs());
    return true;
}

bool trackerSetMovingGnssSecs(uint16_t seconds)
{
    const uint8_t index = findValueIndex(seconds, MOVING_GNSS_PRESETS, 255);
    if (index == 255)
        return false;
    movingGnssIndex = index;
    saveUShort("moveGps", trackerMovingGnssSecs());
    LOG_INFO("Tracker V1.1 setting changed: moving GNSS=%us", (unsigned)trackerMovingGnssSecs());
    return true;
}

bool trackerSetParkGpsSearchSecs(uint16_t seconds)
{
    const uint8_t index = findValueIndex(seconds, PARK_GPS_SEARCH_PRESETS, 255);
    if (index == 255)
        return false;
    parkGpsSearchIndex = index;
    saveUShort("gpsWait", trackerParkGpsSearchSecs());
    LOG_INFO("Tracker V1.1 setting changed: parked GPS search=%us", (unsigned)trackerParkGpsSearchSecs());
    return true;
}

bool trackerSetBleIdleTimeoutSecs(uint16_t seconds)
{
    const uint8_t index = findValueIndex(seconds, BLE_IDLE_PRESETS, 255);
    if (index == 255)
        return false;
    bleIdleIndex = index;
    saveUShort("bleIdle", trackerBleIdleTimeoutSecs());
    LOG_INFO("Tracker V1.1 setting changed: BLE idle timeout=%us", (unsigned)trackerBleIdleTimeoutSecs());
    return true;
}

bool trackerSetBleHardTimeoutSecs(uint16_t seconds)
{
    const uint8_t index = findValueIndex(seconds, BLE_HARD_PRESETS, 255);
    if (index == 255)
        return false;
    bleHardIndex = index;
    saveUShort("bleHard", trackerBleHardTimeoutSecs());
    LOG_INFO("Tracker V1.1 setting changed: BLE hard timeout=%us", (unsigned)trackerBleHardTimeoutSecs());
    return true;
}

bool trackerSetParkIntervalMinutes(uint16_t minutes)
{
    const uint8_t index = findValueIndex(minutes, PARK_PRESETS, 255);
    if (index == 255)
        return false;
    parkIndex = index;
    saveParkMinutes(minutes);
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: park interval=%umin effective=%us", (unsigned)trackerParkIntervalMinutes(),
             (unsigned)trackerEffectiveParkIntervalSecs());
    return true;
}

void trackerCycleMotionSensitivity()
{
    trackerSetMotionSensitivityIndex((uint8_t)((motionIndex + 1U) % (sizeof(MOTION_PRESETS) / sizeof(MOTION_PRESETS[0]))));
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
    saveParkMinutes(trackerParkIntervalMinutes());
    trackerApplyPositionSettings();
    LOG_INFO("Tracker V1.1 setting changed: park interval=%umin effective=%us", (unsigned)trackerParkIntervalMinutes(),
             (unsigned)trackerEffectiveParkIntervalSecs());
}

#endif // HELTEC_TRACKER_V1_1
