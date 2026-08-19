#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "PowerStatus.h"
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

RTC_DATA_ATTR static uint32_t parkedTimerWakeCount = 0;
RTC_DATA_ATTR static uint8_t consecutiveTimerNoFixes = 0;
RTC_DATA_ATTR static bool previousTimerResultValid = false;
RTC_DATA_ATTR static bool previousTimerHadFreshFix = false;

static uint32_t adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
static bool adaptiveGnssInitialized = false;

static bool adaptiveLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;

    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= VEHICLE_LOW_BATTERY_PERCENT;
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

    // PositionModule intentionally clears the local position on every sleepy
    // tracker boot, so the previous timer-cycle result cannot be reconstructed
    // reliably from NodeDB. Consume the explicit RTC-retained result instead.
    if (previousTimerResultValid) {
        if (previousTimerHadFreshFix) {
            consecutiveTimerNoFixes = 0;
        } else if (consecutiveTimerNoFixes < UINT8_MAX) {
            consecutiveTimerNoFixes++;
        }
        previousTimerResultValid = false;
    }

    parkedTimerWakeCount++;

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

void vehicleAdaptiveRecordTimerResult(bool freshFix)
{
    previousTimerHadFreshFix = freshFix;
    previousTimerResultValid = true;
    LOG_DEBUG("Tracker V1.1 adaptive GNSS: remember timer result fresh=%d for next parked wake", freshFix ? 1 : 0);
}

#endif
