#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "NodeDB.h"
#include "PowerStatus.h"
#include "gps/RTC.h"
#include "main.h"

#include <esp_attr.h>
#include <esp_sleep.h>

#ifndef VEHICLE_TIMER_GPS_FULL_WAIT_MS
#define VEHICLE_TIMER_GPS_FULL_WAIT_MS 45000UL
#endif

#ifndef VEHICLE_TIMER_GPS_SHORT_WAIT_MS
#define VEHICLE_TIMER_GPS_SHORT_WAIT_MS 12000UL
#endif

#ifndef VEHICLE_TIMER_GPS_LOW_BATTERY_WAIT_MS
#define VEHICLE_TIMER_GPS_LOW_BATTERY_WAIT_MS 10000UL
#endif

#ifndef VEHICLE_TIMER_GPS_FAILURES_BEFORE_SHORT
#define VEHICLE_TIMER_GPS_FAILURES_BEFORE_SHORT 3U
#endif

#ifndef VEHICLE_TIMER_GPS_FULL_RETRY_EVERY
#define VEHICLE_TIMER_GPS_FULL_RETRY_EVERY 6U
#endif

#ifndef VEHICLE_LOW_BATTERY_PERCENT
#define VEHICLE_LOW_BATTERY_PERCENT 20U
#endif

RTC_DATA_ATTR static uint32_t previousTimerWakeEpoch = 0;
RTC_DATA_ATTR static uint32_t parkedTimerWakeCount = 0;
RTC_DATA_ATTR static uint8_t consecutiveTimerNoFixes = 0;
static uint32_t adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
static bool adaptiveGnssInitialized = false;

static bool adaptiveLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;

    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= VEHICLE_LOW_BATTERY_PERCENT;
}

static bool previousTimerCycleGotFreshFix()
{
    if (previousTimerWakeEpoch == 0 || !nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;

    meshtastic_PositionLite position;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position) || position.time == 0)
        return false;

    // A fix obtained during the previous parked timer cycle must be timestamped
    // at or after the time that previous timer cycle started.
    return position.time >= previousTimerWakeEpoch;
}

void setupVehicleAdaptiveGnss()
{
    if (adaptiveGnssInitialized)
        return;
    adaptiveGnssInitialized = true;

    if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_TIMER) {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
        return;
    }

    if (previousTimerWakeEpoch != 0) {
        if (previousTimerCycleGotFreshFix()) {
            consecutiveTimerNoFixes = 0;
        } else if (consecutiveTimerNoFixes < UINT8_MAX) {
            consecutiveTimerNoFixes++;
        }
    }

    parkedTimerWakeCount++;
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch != 0)
        previousTimerWakeEpoch = nowEpoch;

    if (adaptiveLowBattery()) {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_LOW_BATTERY_WAIT_MS;
    } else if (consecutiveTimerNoFixes < VEHICLE_TIMER_GPS_FAILURES_BEFORE_SHORT) {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
    } else if (VEHICLE_TIMER_GPS_FULL_RETRY_EVERY != 0 &&
               parkedTimerWakeCount % VEHICLE_TIMER_GPS_FULL_RETRY_EVERY == 0) {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
    } else {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_SHORT_WAIT_MS;
    }

    LOG_INFO("Tracker V1.1 adaptive GNSS: timerWake=%u noFixStreak=%u wait=%us%s", (unsigned)parkedTimerWakeCount,
             (unsigned)consecutiveTimerNoFixes, (unsigned)(adaptiveTimerGpsWaitMs / 1000UL),
             adaptiveLowBattery() ? " low-battery" : "");
}

uint32_t vehicleAdaptiveTimerGpsWaitMs()
{
    if (!adaptiveGnssInitialized)
        setupVehicleAdaptiveGnss();
    return adaptiveTimerGpsWaitMs;
}

#endif
