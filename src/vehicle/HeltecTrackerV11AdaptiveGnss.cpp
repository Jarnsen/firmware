#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "NodeDB.h"
#include "PowerStatus.h"
#include "TrackerEnhancements.h"
#include "gps/RTC.h"
#include "main.h"
#include "sleep.h"

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

#ifndef VEHICLE_POSITION_FRESH_SECS
#define VEHICLE_POSITION_FRESH_SECS 60UL
#endif

#ifndef VEHICLE_TTFF_MARGIN_MS
#define VEHICLE_TTFF_MARGIN_MS 5000UL
#endif

#ifndef VEHICLE_TTFF_LOW_BATTERY_MARGIN_MS
#define VEHICLE_TTFF_LOW_BATTERY_MARGIN_MS 3000UL
#endif

#ifndef VEHICLE_TTFF_LOW_BATTERY_MAX_MS
#define VEHICLE_TTFF_LOW_BATTERY_MAX_MS 20000UL
#endif

RTC_DATA_ATTR static uint32_t parkedTimerWakeCount = 0;
RTC_DATA_ATTR static uint8_t consecutiveTimerNoFixes = 0;
RTC_DATA_ATTR static bool previousTimerResultValid = false;
RTC_DATA_ATTR static bool previousTimerHadFreshFix = false;

static uint32_t adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
static bool adaptiveGnssInitialized = false;
static bool currentBootIsTimerWake = false;

static uint32_t clampWait(uint32_t value, uint32_t minimum, uint32_t maximum)
{
    if (value < minimum)
        return minimum;
    if (value > maximum)
        return maximum;
    return value;
}

static bool adaptiveLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;

    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= VEHICLE_LOW_BATTERY_PERCENT;
}

static bool currentTimerCycleHasFreshFix()
{
    if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;

    meshtastic_PositionLite position;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position) || position.time == 0)
        return false;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0 || nowEpoch < position.time)
        return false;

    return (nowEpoch - position.time) <= VEHICLE_POSITION_FRESH_SECS;
}

void vehicleAdaptiveRecordTimerResult(bool freshFix)
{
    previousTimerHadFreshFix = freshFix;
    previousTimerResultValid = true;
    LOG_DEBUG("Tracker V1.1 adaptive GNSS: remember timer result fresh=%d for "
              "next parked wake",
              freshFix ? 1 : 0);
}

class AdaptiveTimerSleepObserver : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!currentBootIsTimerWake || previousTimerResultValid)
            return 0;

        vehicleAdaptiveRecordTimerResult(currentTimerCycleHasFreshFix());
        return 0;
    }
};

static AdaptiveTimerSleepObserver *adaptiveTimerSleepObserver = nullptr;

void setupVehicleAdaptiveGnss()
{
    if (adaptiveGnssInitialized)
        return;
    adaptiveGnssInitialized = true;

    currentBootIsTimerWake = esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER;
    if (!currentBootIsTimerWake) {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
        return;
    }

    // PositionModule intentionally clears the local position on every sleepy
    // tracker boot, so consume the explicit RTC-retained previous-cycle result.
    if (previousTimerResultValid) {
        if (previousTimerHadFreshFix) {
            consecutiveTimerNoFixes = 0;
        } else if (consecutiveTimerNoFixes < UINT8_MAX) {
            consecutiveTimerNoFixes++;
        }
        previousTimerResultValid = false;
    }

    parkedTimerWakeCount++;

    const uint32_t learnedTtff = trackerLearnedTtffMs();

    if (adaptiveLowBattery()) {
        // On low battery keep the window economical, but do not blindly stop at
        // 10 seconds when this particular installation has learned that its GNSS
        // normally needs longer.
        uint32_t lowBatteryTarget = VEHICLE_TIMER_GPS_LOW_BATTERY_WAIT_MS;
        if (learnedTtff != 0)
            lowBatteryTarget = learnedTtff + VEHICLE_TTFF_LOW_BATTERY_MARGIN_MS;
        adaptiveTimerGpsWaitMs =
            clampWait(lowBatteryTarget, VEHICLE_TIMER_GPS_LOW_BATTERY_WAIT_MS, VEHICLE_TTFF_LOW_BATTERY_MAX_MS);
    } else if (consecutiveTimerNoFixes == 0 && learnedTtff != 0) {
        // Successful installations learn their real time-to-first-fix. Add a
        // five-second safety margin and clamp to the existing 12..45 second
        // envelope, so a fast installation stops wasting a fixed 45-second wait.
        adaptiveTimerGpsWaitMs =
            clampWait(learnedTtff + VEHICLE_TTFF_MARGIN_MS, VEHICLE_TIMER_GPS_SHORT_WAIT_MS, VEHICLE_TIMER_GPS_FULL_WAIT_MS);
    } else if (consecutiveTimerNoFixes < VEHICLE_TIMER_GPS_FAILURES_BEFORE_SHORT) {
        // After one or two misses temporarily return to the generous window to
        // recover reliability before deciding the location is persistently poor.
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
    } else if (VEHICLE_TIMER_GPS_FULL_RETRY_EVERY != 0 && parkedTimerWakeCount % VEHICLE_TIMER_GPS_FULL_RETRY_EVERY == 0) {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_FULL_WAIT_MS;
    } else {
        adaptiveTimerGpsWaitMs = VEHICLE_TIMER_GPS_SHORT_WAIT_MS;
    }

    if (adaptiveTimerSleepObserver == nullptr) {
        adaptiveTimerSleepObserver = new AdaptiveTimerSleepObserver();
        adaptiveTimerSleepObserver->observe(&notifyDeepSleep);
    }

    LOG_INFO("Tracker V1.1 adaptive GNSS: timerWake=%u noFixStreak=%u "
             "learnedTTFF=%ums wait=%us%s",
             (unsigned)parkedTimerWakeCount, (unsigned)consecutiveTimerNoFixes, (unsigned)learnedTtff,
             (unsigned)(adaptiveTimerGpsWaitMs / 1000UL), adaptiveLowBattery() ? " low-battery" : "");
}

uint32_t vehicleAdaptiveTimerGpsWaitMs()
{
    if (!adaptiveGnssInitialized)
        setupVehicleAdaptiveGnss();
    return adaptiveTimerGpsWaitMs;
}

#endif
