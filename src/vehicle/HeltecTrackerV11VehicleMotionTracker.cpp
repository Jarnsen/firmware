#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "Default.h"
#include "NodeDB.h"
#include "TrackerServiceSettings.h"
#include "TypeConversions.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "main.h"
#include "modules/PositionModule.h"
#include "sleep.h"

#include <driver/gpio.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>

uint32_t vehicleAdaptiveTimerGpsWaitMs();

#ifndef VEHICLE_MOTION_QUIET_MS
#define VEHICLE_MOTION_QUIET_MS (120UL * 1000UL)
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

#ifndef VEHICLE_FINAL_GPS_WAIT_MS
#define VEHICLE_FINAL_GPS_WAIT_MS 30000UL
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

static bool managedSleepPermission = false;
static bool suppressMotionWakeForSafetySleep = false;
static bool motionLightSleepWakeArmed = false;
static bool motionLightSleepObserversInstalled = false;

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
  uint32_t buttonWakes;
  uint32_t gpioWakes;
  uint32_t confirmedMotionStarts;
  uint32_t rejectedMotionWakes;
  uint32_t bleActivityEvents;
  uint32_t stuckLowEvents;
  uint32_t freshFinalPositionTx;
  uint32_t fallbackFinalPositionTx;
  uint32_t timerFreshPositionTx;
  uint32_t timerFallbackPositionTx;
  uint32_t noFixCycles;
  uint32_t sleepRequestsBlocked;
  uint32_t sleepsAllowed;
  uint32_t lastSleepReason;
};

// Bump whenever the RTC-retained diagnostics layout changes.
static constexpr uint32_t VEHICLE_DIAG_MAGIC = 0x56315453; // "V1TS"
RTC_DATA_ATTR static VehicleDiagnostics vehicleDiag;

static void logVehicleDiagnostics() {
  LOG_INFO("Tracker V1.1 diag: boots=%u motionWake=%u timerWake=%u "
           "buttonWake=%u gpioWake=%u confirmed=%u rejected=%u "
           "BLE=%u stuckLow=%u finalFresh=%u finalFallback=%u timerFresh=%u "
           "timerFallback=%u noFix=%u blocked=%u sleep=%u "
           "lastReason=%u",
           (unsigned)vehicleDiag.boots, (unsigned)vehicleDiag.motionWakes,
           (unsigned)vehicleDiag.timerWakes, (unsigned)vehicleDiag.buttonWakes,
           (unsigned)vehicleDiag.gpioWakes,
           (unsigned)vehicleDiag.confirmedMotionStarts,
           (unsigned)vehicleDiag.rejectedMotionWakes,
           (unsigned)vehicleDiag.bleActivityEvents,
           (unsigned)vehicleDiag.stuckLowEvents,
           (unsigned)vehicleDiag.freshFinalPositionTx,
           (unsigned)vehicleDiag.fallbackFinalPositionTx,
           (unsigned)vehicleDiag.timerFreshPositionTx,
           (unsigned)vehicleDiag.timerFallbackPositionTx,
           (unsigned)vehicleDiag.noFixCycles,
           (unsigned)vehicleDiag.sleepRequestsBlocked,
           (unsigned)vehicleDiag.sleepsAllowed,
           (unsigned)vehicleDiag.lastSleepReason);
}

static bool vehicleUsbPowered() {
  return powerStatus && powerStatus->getHasUSB();
}

static void IRAM_ATTR vehicleMotionISR() { motionEdgeSequence++; }

static uint8_t vehicleMotionConfirmCount() {
  return trackerMotionConfirmCount();
}

static uint32_t vehicleMotionConfirmWindowMs() {
  return trackerMotionConfirmWindowMs();
}

extern "C" void meshtasticVehiclePhoneContact() {
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) &&              \
    !MESHTASTIC_EXCLUDE_BLUETOOTH
  if (nimbleBluetooth && nimbleBluetooth->isConnected()) {
    lastBleActivityMs = millis();
    bleActivitySeenSinceBoot = true;
    vehicleDiag.bleActivityEvents++;
  }
#endif
}

static bool vehicleTrackerModeEnabled() {
  return config.power.is_power_saving &&
         config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

static void clearMotionCandidate() {
  motionCandidateCount = 0;
  motionCandidateStartedMs = 0;
  motionConfirmationPending = false;
}

static void resetFinalPositionState() {
  finalPositionRequested = false;
  finalPositionRequestedAt = 0;
  finalPositionWaitStarted = false;
  finalPositionWaitStartedAt = 0;
}

static void confirmVehicleMotion(uint32_t now) {
  motionSeenSinceBoot = true;
  lastMotionMs = now;
  clearMotionCandidate();
  rejectedMotionWake = false;
  resetFinalPositionState();
  timerPositionRequested = false;
  timerPositionRequestedAt = 0;
  vehicleDiag.confirmedMotionStarts++;
  LOG_INFO("Tracker V1.1: movement confirmed (%u pulses within %ums); "
           "Bluetooth remains off until GPIO0 service",
           (unsigned)vehicleMotionConfirmCount(),
           (unsigned)vehicleMotionConfirmWindowMs());
}

static void initializeVehicleDiagnostics() {
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
    vehicleDiag.buttonWakes++;
    break;
#if defined(ESP_SLEEP_WAKEUP_GPIO)
  case ESP_SLEEP_WAKEUP_GPIO:
    vehicleDiag.gpioWakes++;
    break;
#endif
  default:
    break;
  }
  logVehicleDiagnostics();
}

static void initializeMotionState() {
  if (motionStateInitialized)
    return;

  motionStateInitialized = true;
  bootActivityMs = millis();
  initializeVehicleDiagnostics();

  // Keep GPIO7 at a defined HIGH level even when the optional SW-18010P /
  // external 100 kOhm circuit is not fitted yet. This prevents a floating
  // input from creating an interrupt storm while the GPIO ISR is installed.
  // The external 100 kOhm pull-up remains the preferred hardware bias.
  pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
  (void)digitalRead(VEHICLE_MOTION_WAKE_PIN);
  processedMotionEdgeSequence = motionEdgeSequence;
  attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN),
                  vehicleMotionISR, FALLING);

  if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
    motionCandidateCount = 1;
    motionCandidateStartedMs = millis();
    motionConfirmationPending = true;
    rejectedMotionWake = false;
    LOG_INFO("Tracker V1.1: motion wake candidate on GPIO%d (1/%u)",
             VEHICLE_MOTION_WAKE_PIN, (unsigned)vehicleMotionConfirmCount());
  }

  if (config.device.button_gpio == VEHICLE_MOTION_WAKE_PIN) {
    LOG_WARN("Tracker V1.1: device.button_gpio is GPIO%d; set it to 0 so the "
             "onboard GPIO0 button remains active",
             VEHICLE_MOTION_WAKE_PIN);
  }
}

static bool confirmedMotionStillActive(uint32_t now) {
  return motionSeenSinceBoot &&
         (uint32_t)(now - lastMotionMs) < (uint32_t)VEHICLE_MOTION_QUIET_MS;
}

static void registerVehicleMotionEdges(uint32_t edgeCount) {
  if (edgeCount == 0)
    return;

  const uint32_t now = millis();

  if (confirmedMotionStillActive(now)) {
    lastMotionMs = now;
    clearMotionCandidate();
    rejectedMotionWake = false;
    resetFinalPositionState();
    timerPositionRequested = false;
    timerPositionRequestedAt = 0;
    return;
  }

  if (!motionConfirmationPending ||
      (uint32_t)(now - motionCandidateStartedMs) >
          (uint32_t)vehicleMotionConfirmWindowMs()) {
    motionCandidateCount = 0;
    motionCandidateStartedMs = now;
    motionConfirmationPending = true;
    rejectedMotionWake = false;
  }

  const uint32_t needed =
      vehicleMotionConfirmCount() > motionCandidateCount
          ? (uint32_t)vehicleMotionConfirmCount() - motionCandidateCount
          : 0U;
  const uint32_t accepted = edgeCount < needed ? edgeCount : needed;
  motionCandidateCount = (uint8_t)(motionCandidateCount + accepted);

  if (motionCandidateCount >= vehicleMotionConfirmCount())
    confirmVehicleMotion(now);
}

static void updateMotionCandidateTimeout() {
  if (!motionConfirmationPending)
    return;

  const uint32_t now = millis();
  if ((uint32_t)(now - motionCandidateStartedMs) >=
      (uint32_t)vehicleMotionConfirmWindowMs()) {
    LOG_INFO("Tracker V1.1: rejected vibration candidate (%u/%u pulses)",
             (unsigned)motionCandidateCount,
             (unsigned)vehicleMotionConfirmCount());
    clearMotionCandidate();
    rejectedMotionWake = true;
    vehicleDiag.rejectedMotionWakes++;
  }
}

static void consumeMotionEdges() {
  initializeMotionState();

  const uint32_t currentSequence = motionEdgeSequence;
  const uint32_t newEdges = currentSequence - processedMotionEdgeSequence;
  if (newEdges != 0) {
    processedMotionEdgeSequence = currentSequence;
    LOG_DEBUG("Tracker motion: GPIO%d +%u edge(s), candidate=%u/%u active=%u",
              VEHICLE_MOTION_WAKE_PIN, (unsigned)newEdges,
              (unsigned)motionCandidateCount,
              (unsigned)vehicleMotionConfirmCount(),
              confirmedMotionStillActive(millis()) ? 1U : 0U);
    registerVehicleMotionEdges(newEdges);
  }

  updateMotionCandidateTimeout();
}

static void updateMotionWakePinHealth() {
  initializeMotionState();
  const uint32_t now = millis();

  if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
    if (wakePinLowStartedMs == 0) {
      wakePinLowStartedMs = now ? now : 1;
    } else if (!wakePinStuckLow && (uint32_t)(now - wakePinLowStartedMs) >=
                                       (uint32_t)VEHICLE_MOTION_STUCK_LOW_MS) {
      wakePinStuckLow = true;
      vehicleDiag.stuckLowEvents++;
      LOG_WARN("Tracker V1.1: GPIO%d LOW for %us; disabling motion wake for "
               "this sleep cycle",
               VEHICLE_MOTION_WAKE_PIN,
               (unsigned)(VEHICLE_MOTION_STUCK_LOW_MS / 1000UL));
    }
  } else {
    wakePinLowStartedMs = 0;
    if (wakePinStuckLow) {
      wakePinStuckLow = false;
      LOG_INFO(
          "Tracker V1.1: GPIO%d recovered HIGH; motion wake available again",
          VEHICLE_MOTION_WAKE_PIN);
    }
  }
}

static bool vehicleMotionRecentlyActive() {
  consumeMotionEdges();
  updateMotionWakePinHealth();
  return confirmedMotionStillActive(millis());
}

static bool vehicleMotionConfirmationPending() {
  consumeMotionEdges();
  updateMotionWakePinHealth();
  return motionConfirmationPending;
}

static uint32_t vehicleQuietForMs() {
  consumeMotionEdges();
  updateMotionWakePinHealth();
  return motionSeenSinceBoot ? (uint32_t)(millis() - lastMotionMs)
                             : (uint32_t)(millis() - bootActivityMs);
}

static bool vehicleBleRecentlyActive() {
  if (!bleActivitySeenSinceBoot)
    return false;
  return (uint32_t)(millis() - lastBleActivityMs) <
         (uint32_t)VEHICLE_BLE_ACTIVITY_HOLD_MS;
}

static uint32_t vehicleBleQuietForMs() {
  return bleActivitySeenSinceBoot ? (uint32_t)(millis() - lastBleActivityMs)
                                  : UINT32_MAX;
}

static bool samePositionSample(const meshtastic_PositionLite &a,
                               const meshtastic_PositionLite &b) {
  return a.latitude_i == b.latitude_i && a.longitude_i == b.longitude_i &&
         a.time == b.time;
}

static bool readCurrentVehiclePosition(meshtastic_PositionLite &current) {
  if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
    return false;

  if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), current))
    return false;

  return current.latitude_i != 0 || current.longitude_i != 0;
}

static void observeLatestVehiclePosition() {
  meshtastic_PositionLite current;
  if (!readCurrentVehiclePosition(current))
    return;

  if (!observedPositionValid ||
      !samePositionSample(current, observedPosition)) {
    observedPosition = current;
    observedPositionValid = true;
    lastPositionObservedMs = millis();
  }
}

static bool vehiclePositionIsFresh(const meshtastic_PositionLite &current) {
  const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
  if (current.time != 0 && nowEpoch != 0 && nowEpoch >= current.time)
    return (nowEpoch - current.time) <= VEHICLE_POSITION_FRESH_SECS;

  return observedPositionValid &&
         samePositionSample(current, observedPosition) &&
         (uint32_t)(millis() - lastPositionObservedMs) <=
             (VEHICLE_POSITION_FRESH_SECS * 1000UL);
}

static bool rememberLatestVehiclePosition(bool requireFresh) {
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

static bool restoreParkedPosition() {
  if (!parkedPositionValid || !nodeDB)
    return false;

  meshtastic_Position restored =
      TypeConversions::ConvertToPosition(parkedPosition);
  if (restored.latitude_i == 0 && restored.longitude_i == 0)
    return false;

  nodeDB->setLocalPosition(restored);
  LOG_INFO("Tracker V1.1: restored last parked position as GPS fallback");
  return true;
}

static void armVehicleMotionWake() {
  const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
  if (!rtc_gpio_is_valid_gpio(pin)) {
    LOG_ERROR("Tracker V1.1: GPIO%d is not an RTC wake pin",
              VEHICLE_MOTION_WAKE_PIN);
    return;
  }

  updateMotionWakePinHealth();
  if (wakePinStuckLow || digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
    esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_EXT0);
    LOG_WARN("Tracker V1.1: GPIO%d unavailable at sleep; using timer/button "
             "wake only",
             VEHICLE_MOTION_WAKE_PIN);
    return;
  }

  rtc_gpio_pulldown_dis(pin);
  // Retain a weak internal pull-up as a firmware failsafe. With the external
  // 100 kOhm fitted both pulls simply work in parallel; with no sensor board
  // fitted yet GPIO7 still cannot float and cause false EXT0 wakeups.
  rtc_gpio_pullup_en(pin);

  esp_err_t err = esp_sleep_enable_ext0_wakeup(pin, 0);
  if (err != ESP_OK)
    LOG_ERROR("Tracker V1.1: failed to enable EXT0 wake on GPIO%d: %d",
              VEHICLE_MOTION_WAKE_PIN, err);
}

class TrackerMotionLightSleepBeginObserver : public Observer<void *> {
protected:
  int onNotify(void *) override {
    if (!vehicleTrackerModeEnabled())
      return 0;

    const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    // gpio_wakeup_enable() also changes the normal GPIO interrupt type.
    // Remove our FALLING ISR first so a LOW sensor pulse cannot retrigger
    // the ISR thousands of times while level wake is armed.
    detachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN));
    gpio_wakeup_disable(pin);
    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
    const esp_err_t err = gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);
    if (err == ESP_OK) {
      motionLightSleepWakeArmed = true;
    } else {
      LOG_ERROR(
          "Tracker V1.1: failed to arm GPIO%d light-sleep motion wake: %d",
          VEHICLE_MOTION_WAKE_PIN, (int)err);
      attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN),
                      vehicleMotionISR, FALLING);
    }
    return 0;
  }
};

class TrackerMotionLightSleepEndObserver
    : public Observer<esp_sleep_wakeup_cause_t> {
protected:
  int onNotify(esp_sleep_wakeup_cause_t cause) override {
    if (!motionLightSleepWakeArmed)
      return 0;

    const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    gpio_wakeup_disable(pin);
    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);

    // A GPIO7 level wake represents one physical wake event. Record one
    // candidate edge, then restore the normal edge-triggered ISR. GPIO0
    // button wakes have GPIO7 HIGH and therefore do not count as motion.
    if (cause == ESP_SLEEP_WAKEUP_GPIO &&
        digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)
      motionEdgeSequence++;

    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN),
                    vehicleMotionISR, FALLING);
    motionLightSleepWakeArmed = false;
    return 0;
  }
};

static TrackerMotionLightSleepBeginObserver
    trackerMotionLightSleepBeginObserver;
static TrackerMotionLightSleepEndObserver trackerMotionLightSleepEndObserver;

void variant_shutdown() {
  if (vehicleTrackerModeEnabled() && !suppressMotionWakeForSafetySleep)
    armVehicleMotionWake();
}

extern "C" void vehicleRealDeepSleep(unsigned long, bool,
                                     bool) asm("__real__Z11doDeepSleepmbb");
extern "C" void vehicleWrappedDeepSleep(unsigned long, bool,
                                        bool) asm("__wrap__Z11doDeepSleepmbb");

extern "C" void vehicleWrappedDeepSleep(unsigned long msecToWake,
                                        bool skipPreflight,
                                        bool skipSaveNodeDb) {
  const bool safetyOrShutdownSleep = skipSaveNodeDb || msecToWake == UINT32_MAX;

  if (safetyOrShutdownSleep) {
    suppressMotionWakeForSafetySleep = true;
    vehicleDiag.sleepsAllowed++;
    vehicleRealDeepSleep(msecToWake, skipPreflight, skipSaveNodeDb);
    return;
  }

  if (vehicleTrackerModeEnabled() && !managedSleepPermission) {
    vehicleDiag.sleepRequestsBlocked++;
    LOG_DEBUG("Tracker V1.1: defer ordinary TAK_TRACKER deep sleep to vehicle "
              "state machine");
    return;
  }

  vehicleDiag.sleepsAllowed++;
  logVehicleDiagnostics();
  vehicleRealDeepSleep(msecToWake, skipPreflight, skipSaveNodeDb);
}

static void requestVehicleSleep(VehicleSleepReason reason) {
  if (vehicleUsbPowered())
    return;

  if (vehicleBleRecentlyActive()) {
    LOG_DEBUG("Tracker V1.1: real BLE activity %ums ago, defer managed sleep",
              (unsigned)vehicleBleQuietForMs());
    return;
  }

  updateMotionWakePinHealth();
  if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW && !wakePinStuckLow)
    return;

  const uint32_t sleepMs = Default::getConfiguredOrDefaultMs(
      config.position.position_broadcast_secs);
  vehicleDiag.lastSleepReason =
      wakePinStuckLow ? VEHICLE_SLEEP_STUCK_LOW_FALLBACK : (uint32_t)reason;
  LOG_INFO("Tracker V1.1: sleep reason=%u, interval=%us",
           (unsigned)vehicleDiag.lastSleepReason, (unsigned)(sleepMs / 1000U));

  managedSleepPermission = true;
  doDeepSleep(sleepMs, false, false);
  managedSleepPermission = false;
}

static bool sendFreshPositionIfAvailable(bool timerCycle) {
  if (!rememberLatestVehiclePosition(true))
    return false;

  if (positionModule)
    positionModule->sendOurPosition();

  if (timerCycle)
    vehicleDiag.timerFreshPositionTx++;
  else
    vehicleDiag.freshFinalPositionTx++;
  return true;
}

static bool sendBestAvailablePosition(bool timerCycle) {
  bool havePosition = rememberLatestVehiclePosition(false);
  if (!havePosition)
    havePosition = restoreParkedPosition();

  if (havePosition && positionModule && nodeDB &&
      nodeDB->hasLocalPositionSinceBoot())
    positionModule->sendOurPosition();

  if (havePosition) {
    if (timerCycle)
      vehicleDiag.timerFallbackPositionTx++;
    else
      vehicleDiag.fallbackFinalPositionTx++;
  } else {
    vehicleDiag.noFixCycles++;
    LOG_WARN(
        "Tracker V1.1: no current or cached position available for this cycle");
  }
  return havePosition;
}

class HeltecTrackerV11VehicleMotionThread : public concurrency::OSThread {
public:
  HeltecTrackerV11VehicleMotionThread()
      : concurrency::OSThread("VehicleMotionV11") {}

protected:
  int32_t runOnce() override {
    initializeMotionState();

    if (!vehicleTrackerModeEnabled())
      return 30000;

    observeLatestVehiclePosition();
    updateMotionWakePinHealth();

    // USB/serial is only a sleep veto. Continue consuming GPIO7 edges and
    // running the full vehicle state machine so bench testing behaves like
    // battery operation; requestVehicleSleep() already refuses deep sleep
    // while USB is present.
    const esp_sleep_wakeup_cause_t wakeCause = esp_sleep_get_wakeup_cause();

    // The parked hourly timer cycle never needs BLE. Re-apply this because the
    // normal PowerFSM can briefly enable Bluetooth during boot state
    // transitions.
    if (wakeCause == ESP_SLEEP_WAKEUP_TIMER && !motionSeenSinceBoot)
      setBluetoothEnable(false);

    const bool moving = vehicleMotionRecentlyActive();
    if (moving) {
      resetFinalPositionState();
      timerPositionRequested = false;
      timerPositionRequestedAt = 0;
      rememberLatestVehiclePosition(false);
      return 500;
    }

    if (vehicleMotionConfirmationPending())
      return 250;

    if (wakeCause == ESP_SLEEP_WAKEUP_EXT0 && rejectedMotionWake &&
        !motionSeenSinceBoot) {
      if (vehicleBleRecentlyActive())
        return 1000;

      if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW && !wakePinStuckLow)
        return 250;

      requestVehicleSleep(VEHICLE_SLEEP_FALSE_MOTION);
      return 1000;
    }

    if (wakeCause == ESP_SLEEP_WAKEUP_TIMER && !motionSeenSinceBoot) {
      if (!timerPositionRequested) {
        if (sendFreshPositionIfAvailable(true)) {
          LOG_INFO("Tracker V1.1: timer wake acquired fresh GNSS position");
          timerPositionRequested = true;
          timerPositionRequestedAt = millis();
          return 500;
        }

        const uint32_t timerGpsWaitMs = vehicleAdaptiveTimerGpsWaitMs();
        if ((uint32_t)(millis() - bootActivityMs) < timerGpsWaitMs)
          return 500;

        LOG_WARN("Tracker V1.1: no fresh GNSS fix after %us; using best parked "
                 "fallback",
                 (unsigned)(timerGpsWaitMs / 1000UL));
        sendBestAvailablePosition(true);
        timerPositionRequested = true;
        timerPositionRequestedAt = millis();
        return 500;
      }

      if ((uint32_t)(millis() - timerPositionRequestedAt) >=
          (uint32_t)VEHICLE_SLEEP_AFTER_POSITION_MS)
        requestVehicleSleep(VEHICLE_SLEEP_TIMER_COMPLETE);
      return 500;
    }

    if (vehicleQuietForMs() >= (uint32_t)VEHICLE_MOTION_QUIET_MS) {
      if (!finalPositionRequested) {
        if (sendFreshPositionIfAvailable(false)) {
          LOG_INFO("Tracker V1.1: fresh final GNSS position sent");
          finalPositionRequested = true;
          finalPositionRequestedAt = millis();
          return 500;
        }

        if (!finalPositionWaitStarted) {
          finalPositionWaitStarted = true;
          finalPositionWaitStartedAt = millis();
          LOG_INFO("Tracker V1.1: waiting up to %us for a fresh final GNSS fix",
                   (unsigned)(VEHICLE_FINAL_GPS_WAIT_MS / 1000UL));
          return 500;
        }

        if ((uint32_t)(millis() - finalPositionWaitStartedAt) <
            (uint32_t)VEHICLE_FINAL_GPS_WAIT_MS)
          return 500;

        LOG_WARN("Tracker V1.1: final GNSS wait expired; sending best "
                 "available position");
        sendBestAvailablePosition(false);
        finalPositionRequested = true;
        finalPositionRequestedAt = millis();
        return 500;
      }

      if ((uint32_t)(millis() - finalPositionRequestedAt) >=
          (uint32_t)VEHICLE_SLEEP_AFTER_POSITION_MS)
        requestVehicleSleep(VEHICLE_SLEEP_STATIONARY);
    }

    return 500;
  }
};

static HeltecTrackerV11VehicleMotionThread *vehicleMotionThread = nullptr;

void setupHeltecTrackerV11VehicleMotionTracker() {
  if (!vehicleTrackerModeEnabled())
    return;

  if (!motionLightSleepObserversInstalled) {
    trackerMotionLightSleepBeginObserver.observe(&notifyLightSleep);
    trackerMotionLightSleepEndObserver.observe(&notifyLightSleepEnd);
    motionLightSleepObserversInstalled = true;
  }

  if (vehicleMotionThread == nullptr)
    vehicleMotionThread = new HeltecTrackerV11VehicleMotionThread();
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN
