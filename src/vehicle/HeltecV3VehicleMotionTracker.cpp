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

#ifndef VEHICLE_MOTION_CONFIRM_COUNT
#define VEHICLE_MOTION_CONFIRM_COUNT 3U
#endif

#ifndef VEHICLE_MOTION_CONFIRM_WINDOW_MS
#define VEHICLE_MOTION_CONFIRM_WINDOW_MS 3000UL
#endif

#ifndef VEHICLE_BLE_ACTIVITY_HOLD_MS
#define VEHICLE_BLE_ACTIVITY_HOLD_MS 60000UL
#endif

#ifndef VEHICLE_TIMER_POSITION_DELAY_MS
#define VEHICLE_TIMER_POSITION_DELAY_MS 5000UL
#endif

#ifndef VEHICLE_SLEEP_AFTER_POSITION_MS
#define VEHICLE_SLEEP_AFTER_POSITION_MS 8000UL
#endif

// The SW-18010P is active LOW. The external 100 kOhm pull-up keeps GPIO7 HIGH
// at rest and the optional 100 nF capacitor stretches short vibration pulses.
// Count edges rather than using a bool so several pulses cannot collapse into
// one event while the cooperative thread is sleeping.
static volatile uint32_t motionEdgeSequence = 0;
static uint32_t processedMotionEdgeSequence = 0;
static bool motionStateInitialized = false;
static bool motionSeenSinceBoot = false;
static uint32_t lastMotionMs = 0;
static uint32_t bootActivityMs = 0;

// A parked vehicle must produce several vibration pulses before a new movement
// session is accepted. This rejects a single door slam, accidental bump, etc.
static uint8_t motionCandidateCount = 0;
static uint32_t motionCandidateStartedMs = 0;
static bool motionConfirmationPending = false;
static bool rejectedMotionWake = false;

// Real client traffic received while the BLE link is physically connected.
// Merely staying connected does not refresh this timestamp.
static volatile bool bleActivitySeenSinceBoot = false;
static volatile uint32_t lastBleActivityMs = 0;

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
    motionEdgeSequence++;
}

// PhoneAPI calls this weak hook only after a real client packet is received.
// Checking the physical NimBLE connection here keeps other PhoneAPI transports
// from being mistaken for Bluetooth activity. A passive BLE connection alone
// therefore never keeps the tracker awake indefinitely.
extern "C" void meshtasticVehiclePhoneContact()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isConnected()) {
        lastBleActivityMs = millis();
        bleActivitySeenSinceBoot = true;
    }
#endif
}

static bool vehicleTrackerModeEnabled()
{
    const auto role = config.device.role;
    return config.power.is_power_saving &&
           (role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
            role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER);
}

static void clearMotionCandidate()
{
    motionCandidateCount = 0;
    motionCandidateStartedMs = 0;
    motionConfirmationPending = false;
}

static void confirmVehicleMotion(uint32_t now)
{
    motionSeenSinceBoot = true;
    lastMotionMs = now;
    clearMotionCandidate();
    rejectedMotionWake = false;
    finalPositionRequested = false;
    timerPositionRequested = false;
    LOG_INFO("Vehicle tracker: movement confirmed (%u pulses within %ums)", (unsigned)VEHICLE_MOTION_CONFIRM_COUNT,
             (unsigned)VEHICLE_MOTION_CONFIRM_WINDOW_MS);
}

static void initializeMotionState()
{
    if (motionStateInitialized)
        return;

    motionStateInitialized = true;
    bootActivityMs = millis();

    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT); // external 100 kOhm pull-up
    processedMotionEdgeSequence = motionEdgeSequence;
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), vehicleMotionISR, FALLING);

    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
        // EXT0 LOW is the first pulse. Require two more pulses before declaring
        // that the vehicle is really moving.
        motionCandidateCount = 1;
        motionCandidateStartedMs = millis();
        motionConfirmationPending = true;
        rejectedMotionWake = false;
        LOG_INFO("Vehicle tracker: motion wake candidate on GPIO%d (1/%u)", VEHICLE_MOTION_WAKE_PIN,
                 (unsigned)VEHICLE_MOTION_CONFIRM_COUNT);
    }

    if (config.device.button_gpio == VEHICLE_MOTION_WAKE_PIN) {
        LOG_WARN("Vehicle tracker: device.button_gpio is GPIO%d; set it to 0 so the original GPIO0 button remains active",
                 VEHICLE_MOTION_WAKE_PIN);
    }
}

static bool confirmedMotionStillActive(uint32_t now)
{
    return motionSeenSinceBoot && (uint32_t)(now - lastMotionMs) < (uint32_t)VEHICLE_MOTION_QUIET_MS;
}

static void registerVehicleMotionEdges(uint32_t edgeCount)
{
    if (edgeCount == 0)
        return;

    const uint32_t now = millis();

    // Once driving is confirmed, every later vibration extends the movement
    // session. Re-qualification is only needed after 120 s of confirmed quiet.
    if (confirmedMotionStillActive(now)) {
        lastMotionMs = now;
        clearMotionCandidate();
        rejectedMotionWake = false;
        finalPositionRequested = false;
        timerPositionRequested = false;
        return;
    }

    // If an old candidate window expired before these edges were processed,
    // start a fresh qualification window with the newly observed edges.
    if (!motionConfirmationPending ||
        (uint32_t)(now - motionCandidateStartedMs) > (uint32_t)VEHICLE_MOTION_CONFIRM_WINDOW_MS) {
        motionCandidateCount = 0;
        motionCandidateStartedMs = now;
        motionConfirmationPending = true;
        rejectedMotionWake = false;
    }

    const uint32_t needed = VEHICLE_MOTION_CONFIRM_COUNT > motionCandidateCount
                                ? (uint32_t)VEHICLE_MOTION_CONFIRM_COUNT - motionCandidateCount
                                : 0U;
    const uint32_t accepted = edgeCount < needed ? edgeCount : needed;
    motionCandidateCount = (uint8_t)(motionCandidateCount + accepted);

    if (motionCandidateCount >= VEHICLE_MOTION_CONFIRM_COUNT)
        confirmVehicleMotion(now);
}

static void updateMotionCandidateTimeout()
{
    if (!motionConfirmationPending)
        return;

    const uint32_t now = millis();
    if ((uint32_t)(now - motionCandidateStartedMs) >= (uint32_t)VEHICLE_MOTION_CONFIRM_WINDOW_MS) {
        LOG_INFO("Vehicle tracker: rejected vibration candidate (%u/%u pulses)", (unsigned)motionCandidateCount,
                 (unsigned)VEHICLE_MOTION_CONFIRM_COUNT);
        clearMotionCandidate();
        rejectedMotionWake = true;
    }
}

static void consumeMotionEdges()
{
    initializeMotionState();

    const uint32_t currentSequence = motionEdgeSequence;
    const uint32_t newEdges = currentSequence - processedMotionEdgeSequence;
    if (newEdges != 0) {
        processedMotionEdgeSequence = currentSequence;
        registerVehicleMotionEdges(newEdges);
    }

    updateMotionCandidateTimeout();
}

static bool vehicleMotionRecentlyActive()
{
    consumeMotionEdges();
    return confirmedMotionStillActive(millis());
}

static bool vehicleMotionConfirmationPending()
{
    consumeMotionEdges();
    return motionConfirmationPending;
}

static uint32_t vehicleQuietForMs()
{
    consumeMotionEdges();
    return motionSeenSinceBoot ? (uint32_t)(millis() - lastMotionMs) : (uint32_t)(millis() - bootActivityMs);
}

static bool vehicleBleRecentlyActive()
{
    if (!bleActivitySeenSinceBoot)
        return false;

    return (uint32_t)(millis() - lastBleActivityMs) < (uint32_t)VEHICLE_BLE_ACTIVITY_HOLD_MS;
}

static uint32_t vehicleBleQuietForMs()
{
    return bleActivitySeenSinceBoot ? (uint32_t)(millis() - lastBleActivityMs) : UINT32_MAX;
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

static bool vehicleSleepBlocked()
{
    consumeMotionEdges();

    if (isUSBPowered)
        return true;

    // If the RC pulse stretcher or the vibration contact still holds GPIO7 LOW,
    // entering EXT0 sleep would cause an immediate wake loop.
    if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)
        return true;

    if (motionConfirmationPending)
        return true;

    if (confirmedMotionStillActive(millis()))
        return true;

    if (vehicleBleRecentlyActive())
        return true;

    return false;
}

// main-esp32.cpp provides a weak variant_shutdown(). This strong Heltec-V3
// override adds GPIO7 as an independent EXT0 source while the normal GPIO0
// user button stays on Meshtastic's existing EXT1 wake path.
void variant_shutdown()
{
    if (vehicleTrackerModeEnabled())
        armVehicleMotionWake();
}

// The Heltec-V3 build uses GNU ld --wrap for doDeepSleep(). This lets the
// vehicle tracker reject normal tracker sleep while vibration or real BLE
// traffic is still active, without changing Meshtastic's generic tracker code.
extern "C" void vehicleRealDeepSleep(uint32_t, bool, bool) asm("__real__Z11doDeepSleepjbb");
extern "C" void vehicleWrappedDeepSleep(uint32_t, bool, bool) asm("__wrap__Z11doDeepSleepjbb");

extern "C" void vehicleWrappedDeepSleep(uint32_t msecToWake, bool skipPreflight, bool skipSaveNodeDb)
{
    // Never interfere with explicit shutdown or the low-battery emergency path.
    const bool safetyOrShutdownSleep = skipSaveNodeDb || msecToWake == UINT32_MAX;

    if (!safetyOrShutdownSleep && vehicleTrackerModeEnabled()) {
        initializeMotionState();

        if (vehicleSleepBlocked()) {
            if (isUSBPowered)
                LOG_DEBUG("Vehicle tracker: USB powered, defer tracker deep sleep");
            else if (vehicleBleRecentlyActive())
                LOG_DEBUG("Vehicle tracker: real BLE activity %ums ago, defer tracker deep sleep",
                          (unsigned)vehicleBleQuietForMs());
            else
                LOG_DEBUG("Vehicle tracker: motion/wake pin active, defer tracker deep sleep");
            return;
        }

        // Race-resistant final check. A vibration edge or BLE packet can arrive
        // while the final position is being queued or while sleep preflight is
        // being prepared. Re-sample everything immediately before entering the
        // real Meshtastic deep-sleep path.
        consumeMotionEdges();
        if (vehicleSleepBlocked()) {
            LOG_DEBUG("Vehicle tracker: activity arrived during sleep preflight, abort deep sleep");
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
            return 500;
        }

        // Qualification is intentionally polled faster than the normal idle
        // loop so the 3-second pulse window is observed with little jitter.
        if (vehicleMotionConfirmationPending())
            return 250;

        const esp_sleep_wakeup_cause_t wakeCause = esp_sleep_get_wakeup_cause();

        // An EXT0 wake that never reached the required pulse count is treated
        // as noise. Return to sleep after the 3 s qualification window instead
        // of burning the full 120 s stationary delay.
        if (wakeCause == ESP_SLEEP_WAKEUP_EXT0 && rejectedMotionWake && !motionSeenSinceBoot) {
            if (vehicleBleRecentlyActive())
                return 1000;

            uint32_t sleepMs = Default::getConfiguredOrDefaultMs(config.position.position_broadcast_secs);
            LOG_INFO("Vehicle tracker: false motion wake rejected, returning to sleep for %us", sleepMs / 1000U);
            doDeepSleep(sleepMs, false, false);
            return 1000;
        }

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
            if (vehicleBleRecentlyActive())
                return 1000;

            uint32_t sleepMs = Default::getConfiguredOrDefaultMs(config.position.position_broadcast_secs);
            LOG_INFO("Vehicle tracker: timer wake complete, BLE quiet, sleeping for %us", sleepMs / 1000U);
            doDeepSleep(sleepMs, false, false);
            return 1000;
        }

        // After confirmed movement has been quiet for 120 s, send one final
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
                if (vehicleBleRecentlyActive())
                    return 1000;

                uint32_t sleepMs = Default::getConfiguredOrDefaultMs(config.position.position_broadcast_secs);
                LOG_INFO("Vehicle tracker: stationary and BLE quiet, sleeping for %us", sleepMs / 1000U);
                doDeepSleep(sleepMs, false, false);
            }
        }

        return 500;
    }
};

static HeltecV3VehicleMotionThread *vehicleMotionThread = nullptr;

// Called from setupModules(), after OSThread::setup() and PositionModule creation.
// Avoid constructing an OSThread at static-init time: OSThread intentionally
// asserts until the cooperative scheduler has been initialized.
void setupHeltecV3VehicleMotionTracker()
{
    if (vehicleTrackerModeEnabled() && vehicleMotionThread == nullptr)
        vehicleMotionThread = new HeltecV3VehicleMotionThread();
}

#endif // HELTEC_V3 && VEHICLE_MOTION_WAKE_PIN
