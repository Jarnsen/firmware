#include "configuration.h"
#include "TrackerEnhancements.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "NodeDB.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "main.h"

#include <cmath>
#include <esp_attr.h>
#include <esp_sleep.h>

#ifndef TRACKER_SENSOR_DIAG_MOVE_METERS
#define TRACKER_SENSOR_DIAG_MOVE_METERS 200U
#endif

#ifndef TRACKER_SENSOR_STUCK_LOW_MS
#define TRACKER_SENSOR_STUCK_LOW_MS 30000UL
#endif

#ifndef TRACKER_DIAG_POSITION_FRESH_SECS
#define TRACKER_DIAG_POSITION_FRESH_SECS 60UL
#endif

RTC_DATA_ATTR static uint32_t learnedTtffMs = 0;
RTC_DATA_ATTR static uint32_t enhancementBootCount = 0;
RTC_DATA_ATTR static uint32_t lastFreshFixEpoch = 0;
RTC_DATA_ATTR static bool baselinePositionValid = false;
RTC_DATA_ATTR static meshtastic_PositionLite baselinePosition;
RTC_DATA_ATTR static bool motionWakeSinceBaseline = false;
RTC_DATA_ATTR static bool motionSensorSuspect = false;
RTC_DATA_ATTR static uint32_t missedMovementEvents = 0;

static bool enhancementsInitialized = false;
static bool firstFreshFixHandled = false;
static uint32_t bootStartedMs = 0;
static uint32_t sensorLowStartedMs = 0;
static esp_sleep_wakeup_cause_t bootWakeCause = ESP_SLEEP_WAKEUP_UNDEFINED;
static meshtastic_PositionLite lastObservedPosition;
static bool lastObservedPositionValid = false;

static bool trackerEnhancementsEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

static bool readFreshPosition(meshtastic_PositionLite &position)
{
    if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;

    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position))
        return false;

    if (position.latitude_i == 0 && position.longitude_i == 0)
        return false;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (position.time != 0 && nowEpoch != 0 && nowEpoch >= position.time)
        return (nowEpoch - position.time) <= TRACKER_DIAG_POSITION_FRESH_SECS;

    // If RTC time is not valid yet, a position created since this boot is still
    // useful for TTFF learning and local diagnostics.
    return true;
}

static bool samePosition(const meshtastic_PositionLite &a, const meshtastic_PositionLite &b)
{
    return a.latitude_i == b.latitude_i && a.longitude_i == b.longitude_i && a.time == b.time;
}

static uint32_t distanceMeters(const meshtastic_PositionLite &a, const meshtastic_PositionLite &b)
{
    constexpr double DEG_TO_RAD = 0.017453292519943295;
    constexpr double EARTH_RADIUS_M = 6371000.0;

    const double lat1 = ((double)a.latitude_i / 10000000.0) * DEG_TO_RAD;
    const double lat2 = ((double)b.latitude_i / 10000000.0) * DEG_TO_RAD;
    const double dLat = lat2 - lat1;
    const double dLon = (((double)b.longitude_i - (double)a.longitude_i) / 10000000.0) * DEG_TO_RAD;
    const double x = dLon * std::cos((lat1 + lat2) * 0.5);
    const double d = std::sqrt(dLat * dLat + x * x) * EARTH_RADIUS_M;
    return d > 0.0 ? (uint32_t)d : 0U;
}

static void learnTtff(uint32_t sampleMs)
{
    if (sampleMs < 1000U || sampleMs > 120000U)
        return;

    if (learnedTtffMs == 0)
        learnedTtffMs = sampleMs;
    else
        learnedTtffMs = (learnedTtffMs * 3U + sampleMs) / 4U;

    LOG_INFO("Tracker V1.1 diagnostics: TTFF sample=%ums learned=%ums", (unsigned)sampleMs,
             (unsigned)learnedTtffMs);
}

static void processFreshPosition(const meshtastic_PositionLite &position)
{
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (position.time != 0)
        lastFreshFixEpoch = position.time;
    else if (nowEpoch != 0)
        lastFreshFixEpoch = nowEpoch;

    if (!firstFreshFixHandled) {
        firstFreshFixHandled = true;
        if (bootWakeCause == ESP_SLEEP_WAKEUP_TIMER)
            learnTtff((uint32_t)(millis() - bootStartedMs));
    }

    const bool takTracker = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
    if (!takTracker)
        return;

    if (bootWakeCause == ESP_SLEEP_WAKEUP_TIMER) {
        if (baselinePositionValid && !motionWakeSinceBaseline) {
            const uint32_t moved = distanceMeters(baselinePosition, position);
            if (moved >= TRACKER_SENSOR_DIAG_MOVE_METERS) {
                motionSensorSuspect = true;
                missedMovementEvents++;
                LOG_WARN("Tracker V1.1 sensor self-check: moved %um without GPIO7 wake; inspect SW-18010P/wiring",
                         (unsigned)moved);
            }
        }

        baselinePosition = position;
        baselinePositionValid = true;
        motionWakeSinceBaseline = false;
    } else {
        // During a normal motion wake keep the retained baseline following the
        // vehicle. The latest fresh sample will therefore be available for the
        // next parked timer self-check.
        baselinePosition = position;
        baselinePositionValid = true;
    }
}

static void updateSensorPinHealth(uint32_t now)
{
    if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
        if (sensorLowStartedMs == 0)
            sensorLowStartedMs = now ? now : 1;
        else if ((uint32_t)(now - sensorLowStartedMs) >= TRACKER_SENSOR_STUCK_LOW_MS)
            motionSensorSuspect = true;
    } else {
        sensorLowStartedMs = 0;
    }
}

class TrackerEnhancementsThread : public concurrency::OSThread
{
  public:
    TrackerEnhancementsThread() : concurrency::OSThread("TrackerEnhance") {}

  protected:
    int32_t runOnce() override
    {
        if (!trackerEnhancementsEnabled())
            return 30000;

        updateSensorPinHealth(millis());

        meshtastic_PositionLite position;
        if (readFreshPosition(position) && (!lastObservedPositionValid || !samePosition(position, lastObservedPosition))) {
            lastObservedPosition = position;
            lastObservedPositionValid = true;
            processFreshPosition(position);
        }

        return firstFreshFixHandled ? 2000 : 250;
    }
};

static TrackerEnhancementsThread *enhancementsThread = nullptr;

void setupTrackerEnhancements()
{
    if (enhancementsInitialized || !trackerEnhancementsEnabled())
        return;

    enhancementsInitialized = true;
    bootStartedMs = millis();
    bootWakeCause = esp_sleep_get_wakeup_cause();
    enhancementBootCount++;

    if (bootWakeCause == ESP_SLEEP_WAKEUP_EXT0) {
        motionWakeSinceBaseline = true;
        // A real hardware motion wake proves that the sensor circuit can still
        // pull GPIO7 low, so clear a previous missed-motion warning.
        motionSensorSuspect = false;
    }

    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT);
    enhancementsThread = new TrackerEnhancementsThread();

    LOG_INFO("Tracker V1.1 enhancements: boot=%u wake=%s learnedTTFF=%ums sensor=%s", (unsigned)enhancementBootCount,
             trackerBootWakeReason(), (unsigned)learnedTtffMs, trackerMotionSensorStatus());
}

uint32_t trackerLearnedTtffMs()
{
    return learnedTtffMs;
}

uint32_t trackerLastFixAgeSecs()
{
    if (lastFreshFixEpoch == 0)
        return UINT32_MAX;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0 || nowEpoch < lastFreshFixEpoch)
        return UINT32_MAX;

    return nowEpoch - lastFreshFixEpoch;
}

uint32_t trackerEnhancementBootCount()
{
    return enhancementBootCount;
}

bool trackerMotionSensorSuspect()
{
    return motionSensorSuspect;
}

uint32_t trackerMotionSensorMissedMovementEvents()
{
    return missedMovementEvents;
}

const char *trackerMotionSensorStatus()
{
    return motionSensorSuspect ? "CHECK" : "OK";
}

const char *trackerBootWakeReason()
{
    switch (bootWakeCause) {
    case ESP_SLEEP_WAKEUP_EXT0:
        return "MOTION";
    case ESP_SLEEP_WAKEUP_TIMER:
        return "TIMER";
    case ESP_SLEEP_WAKEUP_EXT1:
        return "BUTTON";
#if defined(ESP_SLEEP_WAKEUP_GPIO)
    case ESP_SLEEP_WAKEUP_GPIO:
        return "GPIO";
#endif
    case ESP_SLEEP_WAKEUP_UNDEFINED:
        return "POWER";
    default:
        return "OTHER";
    }
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN && GPS
