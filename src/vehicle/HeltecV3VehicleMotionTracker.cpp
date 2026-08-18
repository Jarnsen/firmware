#include "configuration.h"

#if defined(HELTEC_V3) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "Default.h"
#include "NodeDB.h"
#include "TypeConversions.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
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

#ifndef VEHICLE_MOTION_STUCK_LOW_MS
#define VEHICLE_MOTION_STUCK_LOW_MS 30000UL
#endif

#ifndef VEHICLE_POSITION_FRESH_SECS
#define VEHICLE_POSITION_FRESH_SECS 60UL
#endif

#ifndef VEHICLE_FINAL_POSITION_WAIT_MS
#define VEHICLE_FINAL_POSITION_WAIT_MS 20000UL
#endif

#ifndef VEHICLE_TIMER_POSITION_DELAY_MS
#define VEHICLE_TIMER_POSITION_DELAY_MS 5000UL
#endif

#ifndef VEHICLE_SLEEP_AFTER_POSITION_MS
#define VEHICLE_SLEEP_AFTER_POSITION_MS 8000UL
#endif

static volatile uint32_t motionEdgeSequence = 0;
static uint32_t processedMotionEdgeSequence = 0;
static bool motionStateInitialized = false;
static bool motionSeenSinceBoot = false;
static uint32_t lastMotionMs = 0;
static uint32_t bootActivityMs = 0;

static uint8_t motionCandidateCount = 0;
static uint32_t motionCandidateStartedMs = 0;
static bool motionConfirmationPending = false;
static bool rejectedMotionWake = false;

static volatile bool bleActivitySeenSinceBoot = false;
static volatile uint32_t lastBleActivityMs = 0;

static uint32_t wakePinLowStartedMs = 0;
static bool wakePinStuckLow = false;

static bool finalPositionRequested = false;
static uint32_t finalPositionRequestedAt = 0;
static bool finalPositionWaitStarted = false;
static uint32_t finalPositionWaitStartedAt = 0;
static bool timerPositionRequested = false;
static uint32_t timerPositionRequestedAt = 0;

static bool observedPositionValid = false;
static meshtastic_PositionLite observedPosition;
static uint32_t lastPositionObservedMs = 0;

RTC_DATA_ATTR static meshtastic_PositionLite parkedPosition;
RTC_DATA_ATTR static bool parkedPositionValid = false;

enum VehicleSleepReason : uint32_t {
    VEHICLE_SLEEP_NONE = 0,
    VEHICLE_SLEEP_FALSE_MOTION = 1,
    VEHICLE_SLEEP_TIMER_COMPLETE = 2,
    VEHICLE_SLEEP_STATIONARY = 3,
    VEHICLE_SLEEP_STUCK_LOW_FALLBACK = 4,
};

struct VehicleDiagnostics {
    uint32_t magic;
    uint32_t boots;
    uint32_t motionWakes;
    uint32_t timerWakes;
    uint32_t ext1Wakes;
    uint32_t confirmedMotionStarts;
    uint32_t rejectedMotionWakes;
    uint32_t bleActivityEvents;
    uint32_t stuckLowEvents;
    uint32_t freshFinalPositionTx;
    uint32_t staleFinalPositionTx;
    uint32_t timerPositionTx;
    uint32_t sleepRequestsBlocked;
    uint32_t sleepsAllowed;
    uint32_t lastSleepReason;
};

static constexpr uint32_t VEHICLE_DIAG_MAGIC = 0x56335452; // "V3TR"
RTC_DATA_ATTR static VehicleDiagnostics vehicleDiag;

static void logVehicleDiagnostics()
{
    LOG_INFO("Vehicle diag: boots=%u motionWake=%u timerWake=%u ext1Wake=%u confirmed=%u rejected=%u BLE=%u stuckLow=%u "
             "finalFresh=%u finalFallback=%u timerTx=%u blocked=%u sleep=%u lastReason=%u",
             (unsigned)vehicleDiag.boots, (unsigned)vehicleDiag.motionWakes, (unsigned)vehicleDiag.timerWakes,
             (unsigned)vehicleDiag.ext1Wakes, (unsigned)vehicleDiag.confirmedMotionStarts,
             (unsigned)vehicleDiag.rejectedMotionWakes, (unsigned)vehicleDiag.bleActivityEvents,
             (unsigned)vehicleDiag.stuckLowEvents, (unsigned)vehicleDiag.freshFinalPositionTx,
             (unsigned)vehicleDiag.staleFinalPositionTx, (unsigned)vehicleDiag.timerPositionTx,
             (unsigned)vehicleDiag.sleepRequestsBlocked, (unsigned)vehicleDiag.sleepsAllowed,
             (unsigned)vehicleDiag.lastSleepReason);
}

static bool vehicleUsbPowered()
{
    return powerStatus && powerStatus->getHasUSB();
}

static void IRAM_ATTR vehicleMotionISR()
{
    motionEdgeSequence++;
}

extern "C" void meshtasticVehiclePhoneContact()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isConnected()) {
        lastBleActivityMs = millis();
        bleActivitySeenSinceBoot = true;
        vehicleDiag.bleActivityEvents++;
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
    finalPositionWaitStarted = false;
    timerPositionRequested = false;
    vehicleDiag.confirmedMotionStarts++;
    LOG_INFO("Vehicle tracker: movement confirmed (%u pulses within %ums)", (unsigned)VEHICLE_MOTION_CONFIRM_COUNT,
             (unsigned)VEHICLE_MOTION_CONFIRM_WINDOW_MS);
}

static void initializeVehicleDiagnostics()
{
    if (vehicleDiag.magic != VEHICLE_DIAG_MAGIC) {
        vehicleDiag = {};
        vehicleDiag.magic = VEHICLE_DIAG_MAGIC;
    }

    vehicleDiag.boots++;
    switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_EXT0:
        vehicleDiag.motionWakes++;
        break;
    case ESP_SLEEP_WAKEUP_TIMER:
        vehicleDiag.timerWakes++;
        break;
    case ESP_SLEEP_WAKEUP_EXT1:
        vehicleDiag.ext1Wakes++;
        break;
    default:
        break;
    }
    logVehicleDiagnostics();
}

static void initializeMotionState()
{
    if (motionStateInitialized)
        return;

    motionStateInitialized = true;
    bootActivityMs = millis();
    initializeVehicleDiagnostics();

    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT); // external 100 kOhm pull-up
    processedMotionEdgeSequence = motionEdgeSequence;
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), vehicleMotionISR, FALLING);

    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
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

    if (confirmedMotionStillActive(now)) {
        lastMotionMs = now;
        clearMotionCandidate();
        rejectedMotionWake = false;
        finalPositionRequested = false;
        finalPositionWaitStarted = false;
        timerPositionRequested = false;
        return;
    }

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
        vehicleDiag.rejectedMotionWakes++;
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

static void updateMotionWakePinHealth()
{
    initializeMotionState();
    const uint32_t now = millis();

    if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
        if (wakePinLowStartedMs == 0) {
            wakePinLowStartedMs = now ? now : 1;
        } else if (!wakePinStuckLow &&
                   (uint32_t)(now - wakePinLowStartedMs) >= (uint32_t)VEHICLE_MOTION_STUCK_LOW_MS) {
            wakePinStuckLow = true;
            vehicleDiag.stuckLowEvents++;
            LOG_WARN("Vehicle tracker: GPIO%d LOW for %us; disabling motion wake for this sleep cycle",
                     VEHICLE_MOTION_WAKE_PIN, (unsigned)(VEHICLE_MOTION_STUCK_LOW_MS / 1000UL));
        }
    } else {
        wakePinLowStartedMs = 0;
        if (wakePinStuckLow) {
            wakePinStuckLow = false;
            LOG_INFO("Vehicle tracker: GPIO%d recovered HIGH; motion wake available again", VEHICLE_MOTION_WAKE_PIN);
        }
    }
}

static bool vehicleMotionRecentlyActive()
{
    consumeMotionEdges();
    updateMotionWakePinHealth();
    return confirmedMotionStillActive(millis());
}

static bool vehicleMotionConfirmationPending()
{
    consumeMotionEdges();
    updateMotionWakePinHealth();
    return motionConfirmationPending;
}

static uint32_t vehicleQuietForMs()
{
    consumeMotionEdges();
    updateMotionWakePinHealth();
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

static bool samePositionSample(const meshtastic_PositionLite &a, const meshtastic_PositionLite &b)
{
    return a.latitude_i == b.latitude_i && a.longitude_i == b.longitude_i && a.time == b.time;
}

static bool readCurrentVehiclePosition(meshtastic_PositionLite &current)
{
    if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;

    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), current))
        return false;

    return current.latitude_i != 0 || current.longitude_i != 0;
}

static void observeLatestVehiclePosition()
{
    meshtastic_PositionLite current;
    if (!readCurrentVehiclePosition(current))
        return;

    if (!observedPositionValid || !samePositionSample(current, observedPosition)) {
        observedPosition = current;
        observedPositionValid = true;
        lastPositionObservedMs = millis();
    }
}

static bool vehiclePositionIsFresh(const meshtastic_PositionLite &current)
{
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (current.time != 0 && nowEpoch != 0 && nowEpoch >= current.time)
        return (nowEpoch - current.time) <= VEHICLE_POSITION_FRESH_SECS;

    return observedPositionValid && samePositionSample(current, observedPosition) &&
           (uint32_t)(millis() - lastPositionObservedMs) <= (VEHICLE_POSITION_FRESH_SECS * 1000UL);
}

static bool rememberLatestVehiclePosition(bool requireFresh)
{
    observeLatestVehiclePosition();

    meshtastic_PositionLite current;
    if (!readCurrentVehiclePosition(current))
        return false;

    if (requireFresh && !vehiclePositionIsFresh(current))
        return false;

    parkedPosition = current;
    parkedPositionValid = true;
    return true;
}

static bool restoreParkedPosition()
{
    if (!parkedPositionValid || !nodeDB)
        return false;

    meshtastic_Position restored = TypeConversions::ConvertToPosition(parkedPosition);
    if (restored.latitude_i == 0 && restored.longitude_i == 0)
        return false;

    nodeDB->setLocalPosition(restored);
    LOG_INFO("Vehicle tracker: restored parked position for timer wake");
    return true;
}

static void armVehicleMotionWake()
{
    const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    if (!rtc_gpio_is_valid_gpio(pin)) {
        LOG_ERROR("Vehicle tracker: GPIO%d is not an RTC wake pin", VEHICLE_MOTION_WAKE_PIN);
        return;
    }

    updateMotionWakePinHealth();
    if (wakePinStuckLow || digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
        esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_EXT0);
        LOG_WARN("Vehicle tracker: GPIO%d unavailable at sleep; using timer/button wake only", VEHICLE_MOTION_WAKE_PIN);
        return;
    }

    rtc_gpio_pulldown_dis(pin);
    rtc_gpio_pullup_dis(pin);

    esp_err_t err = esp_sleep_enable_ext0_wakeup(pin, 0);
    if (err != ESP_OK)
        LOG_ERROR("Vehicle tracker: failed to enable EXT0 wake on GPIO%d: %d", VEHICLE_MOTION_WAKE_PIN, err);
}

static bool vehicleSleepBlocked()
{
    consumeMotionEdges();
    updateMotionWakePinHealth();

    if (vehicleUsbPowered())
        return true;

    if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW && !wakePinStuckLow)
        return true;

    if (motionConfirmationPending)
        return true;

    if (confirmedMotionStillActive(millis()))
        return true;

    if (vehicleBleRecentlyActive())
        return true;

    return false;
}

void variant_shutdown()
{
    if (vehicleTrackerModeEnabled())
        armVehicleMotionWake();
}

// ESP32-S3/newlib uses unsigned long for uint32_t in this build, so the
// mangled doDeepSleep symbol ends in "mbb". The Heltec-V3 variant links with
// --wrap=_Z11doDeepSleepmbb to let this profile defer ordinary tracker sleep.
extern "C" void vehicleRealDeepSleep(unsigned long, bool, bool) asm("__real__Z11doDeepSleepmbb");
extern "C" void vehicleWrappedDeepSleep(unsigned long, bool, bool) asm("__wrap__Z11doDeepSleepmbb");

extern "C" void vehicleWrappedDeepSleep(unsigned long msecToWake, bool skipPreflight, bool skipSaveNodeDb)
{
    const bool safetyOrShutdownSleep = skipSaveNodeDb || msecToWake == UINT32_MAX;

    if (!safetyOrShutdownSleep && vehicleTrackerModeEnabled()) {
        initializeMotionState();

        if (vehicleSleepBlocked()) {
            vehicleDiag.sleepRequestsBlocked++;
            if (vehicleUsbPowered())
                LOG_DEBUG("Vehicle tracker: USB powered, defer tracker deep sleep");
            else if (vehicleBleRecentlyActive())
                LOG_DEBUG("Vehicle tracker: real BLE activity %ums ago, defer tracker deep sleep",
                          (unsigned)vehicleBleQuietForMs());
            else if (wakePinStuckLow)
                LOG_DEBUG("Vehicle tracker: GPIO%d stuck LOW fallback active", VEHICLE_MOTION_WAKE_PIN);
            else
                LOG_DEBUG("Vehicle tracker: motion/wake pin active, defer tracker deep sleep");
            return;
        }

        consumeMotionEdges();
        updateMotionWakePinHealth();
        if (vehicleSleepBlocked()) {
            vehicleDiag.sleepRequestsBlocked++;
            LOG_DEBUG("Vehicle tracker: activity arrived during sleep preflight, abort deep sleep");
            return;
        }
    }

    vehicleDiag.sleepsAllowed++;
    logVehicleDiagnostics();
    vehicleRealDeepSleep(msecToWake, skipPreflight, skipSaveNodeDb);
}

static void requestVehicleSleep(VehicleSleepReason reason)
{
    uint32_t sleepMs = Default::getConfiguredOrDefaultMs(config.position.position_broadcast_secs);
    vehicleDiag.lastSleepReason = wakePinStuckLow ? VEHICLE_SLEEP_STUCK_LOW_FALLBACK : (uint32_t)reason;
    LOG_INFO("Vehicle tracker: sleep reason=%u, interval=%us", (unsigned)vehicleDiag.lastSleepReason,
             (unsigned)(sleepMs / 1000U));
    doDeepSleep(sleepMs, false, false);
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

        observeLatestVehiclePosition();
        updateMotionWakePinHealth();

        if (vehicleUsbPowered())
            return 1000;

        const bool moving = vehicleMotionRecentlyActive();
        if (moving) {
            finalPositionRequested = false;
            finalPositionWaitStarted = false;
            timerPositionRequested = false;
            rememberLatestVehiclePosition(false);
            return 500;
        }

        if (vehicleMotionConfirmationPending())
            return 250;

        const esp_sleep_wakeup_cause_t wakeCause = esp_sleep_get_wakeup_cause();

        if (wakeCause == ESP_SLEEP_WAKEUP_EXT0 && rejectedMotionWake && !motionSeenSinceBoot) {
            if (vehicleBleRecentlyActive())
                return 1000;

            requestVehicleSleep(VEHICLE_SLEEP_FALSE_MOTION);
            return 1000;
        }

        if (wakeCause == ESP_SLEEP_WAKEUP_TIMER && !timerPositionRequested &&
            millis() >= VEHICLE_TIMER_POSITION_DELAY_MS) {
            if (restoreParkedPosition() && positionModule) {
                positionModule->sendOurPosition();
                vehicleDiag.timerPositionTx++;
            }

            timerPositionRequested = true;
            timerPositionRequestedAt = millis();
            return 1000;
        }

        if (timerPositionRequested &&
            (uint32_t)(millis() - timerPositionRequestedAt) >= VEHICLE_SLEEP_AFTER_POSITION_MS) {
            if (vehicleBleRecentlyActive())
                return 1000;

            requestVehicleSleep(VEHICLE_SLEEP_TIMER_COMPLETE);
            return 1000;
        }

        if (vehicleQuietForMs() >= (uint32_t)VEHICLE_MOTION_QUIET_MS) {
            if (motionSeenSinceBoot && !finalPositionRequested) {
                const bool fresh = rememberLatestVehiclePosition(true);

                if (!fresh) {
                    if (!finalPositionWaitStarted) {
                        finalPositionWaitStarted = true;
                        finalPositionWaitStartedAt = millis();
                        LOG_INFO("Vehicle tracker: waiting up to %us for a fresh phone position",
                                 (unsigned)(VEHICLE_FINAL_POSITION_WAIT_MS / 1000UL));
                        return 500;
                    }

                    if ((uint32_t)(millis() - finalPositionWaitStartedAt) < (uint32_t)VEHICLE_FINAL_POSITION_WAIT_MS)
                        return 500;

                    rememberLatestVehiclePosition(false);
                    LOG_WARN("Vehicle tracker: no fresh phone position after %us; sending best available position",
                             (unsigned)(VEHICLE_FINAL_POSITION_WAIT_MS / 1000UL));
                    vehicleDiag.staleFinalPositionTx++;
                } else {
                    vehicleDiag.freshFinalPositionTx++;
                }

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

                requestVehicleSleep(VEHICLE_SLEEP_STATIONARY);
            }
        }

        return 500;
    }
};

static HeltecV3VehicleMotionThread *vehicleMotionThread = nullptr;

void setupHeltecV3VehicleMotionTracker()
{
    if (vehicleTrackerModeEnabled() && vehicleMotionThread == nullptr)
        vehicleMotionThread = new HeltecV3VehicleMotionThread();
}

#endif // HELTEC_V3 && VEHICLE_MOTION_WAKE_PIN
