#include "configuration.h"

#if defined(HELTEC_V3) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "Default.h"
#include "NodeDB.h"
#include "TypeConversions.h"
#include "concurrency/OSThread.h"
#include "main.h"
#include "modules/PositionModule.h"
#include "sleep.h"

#include <driver/rtc_io.h>
#include <esp_sleep.h>

#ifndef VEHICLE_MOTION_QUIET_MS
#define VEHICLE_MOTION_QUIET_MS (120UL * 1000UL)
#endif

#ifndef VEHICLE_TIMER_POSITION_DELAY_MS
#define VEHICLE_TIMER_POSITION_DELAY_MS 5000UL
#endif

#ifndef VEHICLE_SLEEP_AFTER_POSITION_MS
#define VEHICLE_SLEEP_AFTER_POSITION_MS 8000UL
#endif

// The SW-18010P is active LOW. The external 100 kOhm pull-up keeps GPIO7 HIGH
// at rest and the optional 100 nF capacitor stretches short vibration pulses.
static volatile bool motionEdgePending = false;
static bool motionStateInitialized = false;
static bool motionSeenSinceBoot = false;
static uint32_t lastMotionMs = 0;
static uint32_t bootActivityMs = 0;

static bool finalPositionRequested = false;
static uint32_t finalPositionRequestedAt = 0;
static bool timerPositionRequested = false;
static uint32_t timerPositionRequestedAt = 0;

// Keep the last known vehicle position across ESP32-S3 deep-sleep resets.
// This intentionally survives timed sleep, but is cleared by a full power loss.
RTC_DATA_ATTR static meshtastic_PositionLite parkedPosition;
RTC_DATA_ATTR static bool parkedPositionValid = false;

static void IRAM_ATTR vehicleMotionISR()
{
    motionEdgePending = true;
}

static bool vehicleTrackerModeEnabled()
{
    const auto role = config.device.role;
    return config.power.is_power_saving &&
           (role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
            role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER);
}

static void initializeMotionState()
{
    if (motionStateInitialized)
        return;

    motionStateInitialized = true;
    bootActivityMs = millis();

    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT); // external 100 kOhm pull-up
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), vehicleMotionISR, FALLING);

    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
        motionSeenSinceBoot = true;
        lastMotionMs = millis();
        LOG_INFO("Vehicle tracker: woke by motion on GPIO%d", VEHICLE_MOTION_WAKE_PIN);
    }

    if (config.device.button_gpio == VEHICLE_MOTION_WAKE_PIN) {
        LOG_WARN("Vehicle tracker: device.button_gpio is GPIO%d; set it to 0 so the original GPIO0 button remains active",
                 VEHICLE_MOTION_WAKE_PIN);
    }
}

static void consumeMotionEdge()
{
    initializeMotionState();
    if (motionEdgePending) {
        motionEdgePending = false;
        motionSeenSinceBoot = true;
        lastMotionMs = millis();
        finalPositionRequested = false;
        timerPositionRequested = false;
    }
}

static bool vehicleMotionRecentlyActive()
{
    consumeMotionEdge();
    if (!motionSeenSinceBoot)
        return false;
    return (uint32_t)(millis() - lastMotionMs) < (uint32_t)VEHICLE_MOTION_QUIET_MS;
}

static uint32_t vehicleQuietForMs()
{
    consumeMotionEdge();
    return motionSeenSinceBoot ? (uint32_t)(millis() - lastMotionMs) : (uint32_t)(millis() - bootActivityMs);
}

static void armVehicleMotionWake()
{
    const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    if (!rtc_gpio_is_valid_gpio(pin)) {
        LOG_ERROR("Vehicle tracker: GPIO%d is not an RTC wake pin", VEHICLE_MOTION_WAKE_PIN);
        return;
    }

    // External 100 kOhm pull-up defines the idle HIGH level. Do not enable the
    // internal pull-up here, because it would shorten the 100 kOhm/100 nF pulse stretcher.
    rtc_gpio_pulldown_dis(pin);
    rtc_gpio_pullup_dis(pin);

    esp_err_t err = esp_sleep_enable_ext0_wakeup(pin, 0); // active LOW
    if (err != ESP_OK)
        LOG_ERROR("Vehicle tracker: failed to enable EXT0 wake on GPIO%d: %d", VEHICLE_MOTION_WAKE_PIN, err);
}

static void rememberLatestVehiclePosition()
{
    if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return;

    meshtastic_PositionLite current;
    if (nodeDB->copyNodePosition(nodeDB->getNodeNum(), current) &&
        (current.latitude_i != 0 || current.longitude_i != 0)) {
        parkedPosition = current;
        parkedPositionValid = true;
    }
}

static bool restoreParkedPosition()
{
    if (!parkedPositionValid || !nodeDB)
        return false;

    meshtastic_Position restored = TypeConversions::ConvertToPosition(parkedPosition);
    if (restored.latitude_i == 0 && restored.longitude_i == 0)
        return false;

    // Mark it as a local position for this boot so PositionModule can deliberately
    // re-broadcast the last parked position after an hourly TIMER wake.
    nodeDB->setLocalPosition(restored);
    LOG_INFO("Vehicle tracker: restored parked position for timer wake");
    return true;
}

// main-esp32.cpp provides a weak variant_shutdown(). This strong Heltec-V3
// override adds GPIO7 as an independent EXT0 source while the normal GPIO0
// user button stays on Meshtastic's existing EXT1 wake path.
void variant_shutdown()
{
    armVehicleMotionWake();
}

// The Heltec-V3 build uses GNU ld --wrap for doDeepSleep(). This lets the
// vehicle tracker reject sleep while vibration is still being detected,
// without changing Meshtastic's generic tracker/position code.
extern "C" void vehicleRealDeepSleep(uint32_t, bool, bool) asm("__real__Z11doDeepSleepjbb");
extern "C" void vehicleWrappedDeepSleep(uint32_t, bool, bool) asm("__wrap__Z11doDeepSleepjbb");

extern "C" void vehicleWrappedDeepSleep(uint32_t msecToWake, bool skipPreflight, bool skipSaveNodeDb)
{
    if (vehicleTrackerModeEnabled()) {
        initializeMotionState();

        // USB is treated as service/configuration mode: never disappear into
        // deep sleep while the board is connected to a computer/charger.
        if (isUSBPowered) {
            LOG_DEBUG("Vehicle tracker: USB powered, defer deep sleep");
            return;
        }

        if (vehicleMotionRecentlyActive()) {
            LOG_DEBUG("Vehicle tracker: motion active, defer deep sleep");
            return;
        }
    }

    vehicleRealDeepSleep(msecToWake, skipPreflight, skipSaveNodeDb);
}

class HeltecV3VehicleMotionThread : public concurrency::OSThread
{
  public:
    HeltecV3VehicleMotionThread() : concurrency::OSThread("VehicleMotion") {}

  protected:
    int32_t runOnce() override
    {
        initializeMotionState();

        if (!vehicleTrackerModeEnabled())
            return 30000;

        // Keep the freshest phone-provided position in RTC memory while awake.
        rememberLatestVehiclePosition();

        if (isUSBPowered)
            return 1000;

        const bool moving = vehicleMotionRecentlyActive();
        if (moving) {
            finalPositionRequested = false;
            timerPositionRequested = false;
            return 1000;
        }

        const esp_sleep_wakeup_cause_t wakeCause = esp_sleep_get_wakeup_cause();

        // Stationary timed wake: re-send the last parked position once, then
        // return to the configured tracker sleep interval. The V3 has no GNSS,
        // so this is deliberately the cached parked position until the phone
        // supplies a fresh one on the next movement wake.
        if (wakeCause == ESP_SLEEP_WAKEUP_TIMER && !timerPositionRequested &&
            millis() >= VEHICLE_TIMER_POSITION_DELAY_MS) {
            if (restoreParkedPosition() && positionModule)
                positionModule->sendOurPosition();

            timerPositionRequested = true;
            timerPositionRequestedAt = millis();
            return 1000;
        }

        if (timerPositionRequested &&
            (uint32_t)(millis() - timerPositionRequestedAt) >= VEHICLE_SLEEP_AFTER_POSITION_MS) {
            uint32_t sleepMs = Default::getConfiguredOrDefaultMs(config.position.position_broadcast_secs);
            LOG_INFO("Vehicle tracker: timer wake complete, sleeping for %us", sleepMs / 1000U);
            doDeepSleep(sleepMs, false, false);
            return 1000;
        }

        // After the vibration line has been quiet long enough, send one final
        // fresh phone position (when available) before sleeping.
        if (vehicleQuietForMs() >= (uint32_t)VEHICLE_MOTION_QUIET_MS) {
            if (motionSeenSinceBoot && !finalPositionRequested) {
                rememberLatestVehiclePosition();
                if (positionModule && nodeDB && nodeDB->hasLocalPositionSinceBoot())
                    positionModule->sendOurPosition();

                finalPositionRequested = true;
                finalPositionRequestedAt = millis();
                return 1000;
            }

            if (!motionSeenSinceBoot ||
                (finalPositionRequested &&
                 (uint32_t)(millis() - finalPositionRequestedAt) >= VEHICLE_SLEEP_AFTER_POSITION_MS)) {
                uint32_t sleepMs = Default::getConfiguredOrDefaultMs(config.position.position_broadcast_secs);
                LOG_INFO("Vehicle tracker: stationary, sleeping for %us", sleepMs / 1000U);
                doDeepSleep(sleepMs, false, false);
            }
        }

        return 1000;
    }
};

static HeltecV3VehicleMotionThread heltecV3VehicleMotionThread;

#endif // HELTEC_V3 && VEHICLE_MOTION_WAKE_PIN
