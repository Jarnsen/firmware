#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "NodeDB.h"
#include "PowerStatus.h"
#include "TrackerEnhancements.h"
#include "TrackerServiceSettings.h"
#include "TrackerStatusModule.h"
#include "TypeConversions.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "main.h"
#include "modules/PositionModule.h"
#include "sleep.h"
#include "target_specific.h"
#include "vehicle/TrackerCommonPolicy.h"

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#include <atomic>
#include <driver/gpio.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>

void setupVehicleAdaptiveGnss();
uint32_t vehicleAdaptiveTimerGpsWaitMs();
void vehicleAdaptiveRecordTimerResult(bool freshFix);

#ifndef TRACKER_COMMON_SERVICE_IDLE_MS
#define TRACKER_COMMON_SERVICE_IDLE_MS (120UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_SERVICE_MAX_MS
#define TRACKER_COMMON_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_DISPLAY_MS
#define TRACKER_COMMON_DISPLAY_MS (20UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_LOW_BATTERY_DISPLAY_MS
#define TRACKER_COMMON_LOW_BATTERY_DISPLAY_MS (10UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_LOW_BATTERY_PERCENT
#define TRACKER_COMMON_LOW_BATTERY_PERCENT 20U
#endif
#ifndef TRACKER_COMMON_MOTION_QUIET_MS
#define TRACKER_COMMON_MOTION_QUIET_MS (120UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_FINAL_GPS_WAIT_MS
#define TRACKER_COMMON_FINAL_GPS_WAIT_MS (30UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_SLEEP_AFTER_POSITION_MS
#define TRACKER_COMMON_SLEEP_AFTER_POSITION_MS 8000UL
#endif
#ifndef TRACKER_COMMON_POSITION_FRESH_SECS
#define TRACKER_COMMON_POSITION_FRESH_SECS 60UL
#endif
#ifndef TRACKER_COMMON_MOTION_STUCK_LOW_MS
#define TRACKER_COMMON_MOTION_STUCK_LOW_MS (30UL * 1000UL)
#endif
#ifndef TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD
#define TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD 3U
#endif
#ifndef TRACKER_COMMON_BLE_ACTIVITY_WINDOW_MS
#define TRACKER_COMMON_BLE_ACTIVITY_WINDOW_MS (10UL * 1000UL)
#endif

namespace
{
std::atomic<uint32_t> rawBleActivitySequence{0};
uint32_t consumedBleActivitySequence = 0;
uint8_t bleBurstCount = 0;
uint32_t bleBurstStartedMs = 0;

volatile uint32_t motionEdgeSequence = 0;
uint32_t processedMotionEdgeSequence = 0;
uint8_t motionCandidateCount = 0;
uint32_t motionCandidateStartedMs = 0;
bool motionCandidatePending = false;
bool motionActive = false;
uint32_t lastMotionMs = 0;
uint32_t bootActivityMs = 0;
bool parked = false;
bool motionPinStuckLow = false;
uint32_t motionPinLowSinceMs = 0;

bool finalPositionRequested = false;
uint32_t finalPositionRequestedAtMs = 0;
uint32_t finalPositionWaitStartedMs = 0;
bool timerPositionRequested = false;
uint32_t timerPositionRequestedAtMs = 0;
uint32_t lastPositionHeartbeatEpoch = 0;

bool serviceActive = false;
bool displayVisible = false;
bool bootHandoffComplete = false;
uint32_t serviceStartedMs = 0;
uint32_t serviceLastActivityMs = 0;
uint32_t displayStartedMs = 0;
uint32_t displayWindowMs = TRACKER_COMMON_DISPLAY_MS;
bool buttonWasPressed = false;
bool openedServiceThisPress = false;
uint32_t buttonPressedSinceMs = 0;
uint32_t buttonHighSinceMs = 0;

RTC_DATA_ATTR meshtastic_PositionLite retainedLastPosition;
RTC_DATA_ATTR bool retainedLastPositionValid = false;

bool trackerRoleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

bool trackerUsesDeepSleep()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

bool lowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;
    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= TRACKER_COMMON_LOW_BATTERY_PERCENT;
}

gpio_num_t serviceButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);
#else
    return GPIO_NUM_NC;
#endif
}

bool usbPowered()
{
    return powerStatus && powerStatus->getHasUSB();
}

void IRAM_ATTR motionISR()
{
    motionEdgeSequence++;
}

bool readCurrentPosition(meshtastic_PositionLite &position)
{
    if (!nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return false;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position))
        return false;
    return position.latitude_i != 0 || position.longitude_i != 0;
}

bool positionIsFresh()
{
    meshtastic_PositionLite position;
    if (!readCurrentPosition(position))
        return false;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (position.time != 0 && nowEpoch != 0 && nowEpoch >= position.time)
        return (nowEpoch - position.time) <= TRACKER_COMMON_POSITION_FRESH_SECS;

    const uint32_t age = trackerLastFixAgeSecs();
    return age != UINT32_MAX && age <= TRACKER_COMMON_POSITION_FRESH_SECS;
}

bool rememberCurrentPosition()
{
    meshtastic_PositionLite position;
    if (!readCurrentPosition(position))
        return false;
    retainedLastPosition = position;
    retainedLastPositionValid = true;
    return true;
}

bool restoreRetainedPosition()
{
    if (!retainedLastPositionValid || !nodeDB)
        return false;
    if (retainedLastPosition.latitude_i == 0 && retainedLastPosition.longitude_i == 0)
        return false;

    meshtastic_Position restored = TypeConversions::ConvertToPosition(retainedLastPosition);
    nodeDB->setLocalPosition(restored);
    return true;
}

bool sendFreshPosition(bool timerCycle)
{
    if (!positionIsFresh())
        return false;

    rememberCurrentPosition();
    if (positionModule)
        positionModule->sendOurPosition();
    if (timerCycle)
        vehicleAdaptiveRecordTimerResult(true);
    return true;
}

bool sendBestPosition(bool timerCycle)
{
    bool havePosition = rememberCurrentPosition();
    if (!havePosition)
        havePosition = restoreRetainedPosition();

    if (havePosition && positionModule)
        positionModule->sendOurPosition();
    if (timerCycle)
        vehicleAdaptiveRecordTimerResult(false);
    return havePosition;
}

void bluetoothOn()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    config.bluetooth.enabled = true;
    if (!nimbleBluetooth || !nimbleBluetooth->isActive())
        setBluetoothEnable(true);
#else
    config.bluetooth.enabled = true;
    setBluetoothEnable(true);
#endif
}

void bluetoothOff()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    config.bluetooth.enabled = false;
    if (nimbleBluetooth && nimbleBluetooth->isActive())
        nimbleBluetooth->deinit();
#else
    config.bluetooth.enabled = false;
    setBluetoothEnable(false);
#endif
}

bool displayWindowActive()
{
    return serviceActive && displayVisible && displayStartedMs != 0 &&
           (uint32_t)(millis() - displayStartedMs) < displayWindowMs;
}

void showTrackerScreen()
{
    if (!serviceActive)
        return;

    displayWindowMs = lowBattery() ? TRACKER_COMMON_LOW_BATTERY_DISPLAY_MS : TRACKER_COMMON_DISPLAY_MS;
    displayStartedMs = millis() ? millis() : 1;
    displayVisible = true;

    if (!bootHandoffComplete)
        return;

    if (screen) {
        screen->setOn(true);
        trackerStatusRequestFocus();
        screen->runNow();
    }
}

void closeDisplay()
{
    displayVisible = false;
    displayStartedMs = 0;
    if (screen && screen->isScreenOn())
        screen->setOn(false);
}

void startService()
{
    const uint32_t now = millis();
    serviceActive = true;
    serviceStartedMs = now;
    serviceLastActivityMs = now;
    bleBurstCount = 0;
    bleBurstStartedMs = 0;
    bluetoothOn();
    showTrackerScreen();
    LOG_INFO("Tracker service: GPIO0 opened native Meshtastic UI + Bluetooth; idle=%us, activity=%u/%us, hard-cap=%us",
             (unsigned)(TRACKER_COMMON_SERVICE_IDLE_MS / 1000UL), (unsigned)TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD,
             (unsigned)(TRACKER_COMMON_BLE_ACTIVITY_WINDOW_MS / 1000UL),
             (unsigned)(TRACKER_COMMON_SERVICE_MAX_MS / 1000UL));
}

void stopService()
{
    if (!serviceActive)
        return;

    serviceActive = false;
    bluetoothOff();
    closeDisplay();
    trackerApplyPositionSettings();
    LOG_INFO("Tracker service: native UI/Bluetooth window complete");
}

bool bootWasUserWake()
{
    const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    if (cause == ESP_SLEEP_WAKEUP_EXT1)
        return true;
#if defined(ESP_SLEEP_WAKEUP_GPIO)
    if (cause == ESP_SLEEP_WAKEUP_GPIO)
        return true;
#endif
    return false;
}

void processBleActivity(uint32_t now)
{
    const uint32_t current = rawBleActivitySequence.load();
    const uint32_t newEvents = current - consumedBleActivitySequence;
    if (newEvents == 0)
        return;
    consumedBleActivitySequence = current;

    if (!serviceActive)
        return;

    if (bleBurstStartedMs == 0 || (uint32_t)(now - bleBurstStartedMs) > TRACKER_COMMON_BLE_ACTIVITY_WINDOW_MS) {
        bleBurstStartedMs = now ? now : 1;
        bleBurstCount = 0;
    }

    const uint32_t room = TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD > bleBurstCount
                              ? TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD - bleBurstCount
                              : 0U;
    const uint32_t accepted = newEvents < room ? newEvents : room;
    bleBurstCount = (uint8_t)(bleBurstCount + accepted);

    if (bleBurstCount >= TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD) {
        serviceLastActivityMs = now;
        bleBurstCount = 0;
        bleBurstStartedMs = 0;
        LOG_DEBUG("Tracker service: active BLE burst detected; 120s idle timer reset");
    }
}

void resetFinalPositionState()
{
    finalPositionRequested = false;
    finalPositionRequestedAtMs = 0;
    finalPositionWaitStartedMs = 0;
}

void confirmMotion(uint32_t now)
{
    motionActive = true;
    parked = false;
    lastMotionMs = now;
    motionCandidateCount = 0;
    motionCandidateStartedMs = 0;
    motionCandidatePending = false;
    timerPositionRequested = false;
    timerPositionRequestedAtMs = 0;
    resetFinalPositionState();
    trackerStatusSetMotionActive(true);
    LOG_INFO("Tracker V1.1: movement confirmed (%u pulses within %ums); Bluetooth remains off unless GPIO0 service is open",
             (unsigned)trackerMotionConfirmCount(), (unsigned)trackerMotionConfirmWindowMs());
}

void processMotionPinHealth(uint32_t now)
{
    if (digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW) {
        if (motionPinLowSinceMs == 0) {
            motionPinLowSinceMs = now ? now : 1;
        } else if (!motionPinStuckLow &&
                   (uint32_t)(now - motionPinLowSinceMs) >= TRACKER_COMMON_MOTION_STUCK_LOW_MS) {
            motionPinStuckLow = true;
            gpio_wakeup_disable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN);
            LOG_WARN("Tracker V1.1: GPIO%d LOW for %us; motion wake disabled until pin recovers",
                     VEHICLE_MOTION_WAKE_PIN, (unsigned)(TRACKER_COMMON_MOTION_STUCK_LOW_MS / 1000UL));
        }
    } else {
        motionPinLowSinceMs = 0;
        if (motionPinStuckLow) {
            motionPinStuckLow = false;
            gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);
            LOG_INFO("Tracker V1.1: GPIO%d recovered HIGH; motion wake restored", VEHICLE_MOTION_WAKE_PIN);
        }
    }
}

void processMotion(uint32_t now)
{
    const uint32_t current = motionEdgeSequence;
    const uint32_t newEdges = current - processedMotionEdgeSequence;
    processedMotionEdgeSequence = current;

    if (newEdges != 0) {
        LOG_DEBUG("Tracker motion: GPIO%d +%u edge(s), candidate=%u/%u active=%u", VEHICLE_MOTION_WAKE_PIN,
                  (unsigned)newEdges, (unsigned)motionCandidateCount, (unsigned)trackerMotionConfirmCount(),
                  motionActive ? 1U : 0U);

        if (motionActive) {
            lastMotionMs = now;
            resetFinalPositionState();
        } else {
            if (!motionCandidatePending ||
                (uint32_t)(now - motionCandidateStartedMs) > trackerMotionConfirmWindowMs()) {
                motionCandidateCount = 0;
                motionCandidateStartedMs = now;
                motionCandidatePending = true;
            }

            const uint32_t needed = trackerMotionConfirmCount() > motionCandidateCount
                                        ? (uint32_t)trackerMotionConfirmCount() - motionCandidateCount
                                        : 0U;
            const uint32_t accepted = newEdges < needed ? newEdges : needed;
            motionCandidateCount = (uint8_t)(motionCandidateCount + accepted);
            if (motionCandidateCount >= trackerMotionConfirmCount())
                confirmMotion(now);
        }
    }

    if (motionCandidatePending &&
        (uint32_t)(now - motionCandidateStartedMs) >= trackerMotionConfirmWindowMs()) {
        LOG_DEBUG("Tracker V1.1: rejected vibration candidate (%u/%u pulses)", (unsigned)motionCandidateCount,
                  (unsigned)trackerMotionConfirmCount());
        motionCandidateCount = 0;
        motionCandidateStartedMs = 0;
        motionCandidatePending = false;
    }

    processMotionPinHealth(now);
}

void armDeepSleepMotionWake()
{
    const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    if (!rtc_gpio_is_valid_gpio(pin) || motionPinStuckLow || digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW)
        return;

    rtc_gpio_pulldown_dis(pin);
    rtc_gpio_pullup_en(pin);
    const esp_err_t err = esp_sleep_enable_ext0_wakeup(pin, 0);
    if (err != ESP_OK)
        LOG_ERROR("Tracker V1.1: failed to enable deep-sleep motion wake on GPIO%d: %d", VEHICLE_MOTION_WAKE_PIN, err);
}

extern "C" void trackerRealDeepSleep(unsigned long, bool, bool) asm("__real__Z11doDeepSleepmbb");

void enterParkedState(const char *reason)
{
    if (serviceActive)
        return;

    if (trackerUsesDeepSleep()) {
        if (usbPowered())
            return; // USB is a test/maintenance veto only.

        rememberCurrentPosition();
        bluetoothOff();
        closeDisplay();
        trackerStatusSetMotionActive(false);
        armDeepSleepMotionWake();

        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;
        LOG_INFO("Tracker V1.1: %s; TAK_TRACKER entering deep sleep for %us", reason,
                 (unsigned)(sleepMs / 1000UL));
        trackerRealDeepSleep(sleepMs, false, false);
        return;
    }

    if (!parked) {
        parked = true;
        motionActive = false;
        trackerStatusSetMotionActive(false);
        resetFinalPositionState();
        LOG_INFO("Tracker V1.1: %s; TAK returning to always-listening light sleep", reason);
    }
}

void processStationaryFinalPosition(uint32_t now)
{
    if (!motionActive)
        return;
    if ((uint32_t)(now - lastMotionMs) < TRACKER_COMMON_MOTION_QUIET_MS)
        return;

    if (!finalPositionRequested) {
        if (sendFreshPosition(false)) {
            finalPositionRequested = true;
            finalPositionRequestedAtMs = now;
            LOG_INFO("Tracker V1.1: 120s motion quiet; fresh final position sent");
            return;
        }

        if (finalPositionWaitStartedMs == 0) {
            finalPositionWaitStartedMs = now ? now : 1;
            LOG_INFO("Tracker V1.1: 120s motion quiet; waiting up to %us for fresh final GNSS fix",
                     (unsigned)(TRACKER_COMMON_FINAL_GPS_WAIT_MS / 1000UL));
            return;
        }

        if ((uint32_t)(now - finalPositionWaitStartedMs) < TRACKER_COMMON_FINAL_GPS_WAIT_MS)
            return;

        LOG_WARN("Tracker V1.1: final GNSS wait expired; sending best available position");
        sendBestPosition(false);
        finalPositionRequested = true;
        finalPositionRequestedAtMs = now;
        return;
    }

    if ((uint32_t)(now - finalPositionRequestedAtMs) >= TRACKER_COMMON_SLEEP_AFTER_POSITION_MS)
        enterParkedState("final position complete");
}

void processColdBootParking(uint32_t now)
{
    if (motionActive || parked || motionCandidatePending || serviceActive)
        return;
    if ((uint32_t)(now - bootActivityMs) < TRACKER_COMMON_MOTION_QUIET_MS)
        return;

    if (!finalPositionRequested) {
        if (sendFreshPosition(false)) {
            finalPositionRequested = true;
            finalPositionRequestedAtMs = now;
            return;
        }

        if (finalPositionWaitStartedMs == 0) {
            finalPositionWaitStartedMs = now ? now : 1;
            return;
        }
        if ((uint32_t)(now - finalPositionWaitStartedMs) < TRACKER_COMMON_FINAL_GPS_WAIT_MS)
            return;

        sendBestPosition(false);
        finalPositionRequested = true;
        finalPositionRequestedAtMs = now;
        return;
    }

    if ((uint32_t)(now - finalPositionRequestedAtMs) >= TRACKER_COMMON_SLEEP_AFTER_POSITION_MS)
        enterParkedState("stationary startup complete");
}

void processDeepSleepTimerCycle(uint32_t now)
{
    if (!trackerUsesDeepSleep() || esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_TIMER || motionActive || serviceActive)
        return;

    if (!timerPositionRequested) {
        if (sendFreshPosition(true)) {
            timerPositionRequested = true;
            timerPositionRequestedAtMs = now;
            LOG_INFO("Tracker V1.1: parked timer wake acquired fresh GNSS position");
            return;
        }

        if ((uint32_t)(now - bootActivityMs) < vehicleAdaptiveTimerGpsWaitMs())
            return;

        LOG_WARN("Tracker V1.1: parked timer wake has no fresh GNSS fix; using best stored position");
        sendBestPosition(true);
        timerPositionRequested = true;
        timerPositionRequestedAtMs = now;
        return;
    }

    if ((uint32_t)(now - timerPositionRequestedAtMs) >= TRACKER_COMMON_SLEEP_AFTER_POSITION_MS)
        enterParkedState("park heartbeat complete");
}

void updateLightSleepHeartbeat()
{
    if (trackerUsesDeepSleep() || !parked || motionActive || serviceActive || !positionModule)
        return;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0)
        return;

    if (lastPositionHeartbeatEpoch == 0) {
        lastPositionHeartbeatEpoch = nowEpoch;
        return;
    }

    const uint32_t heartbeatSecs = trackerEffectiveParkIntervalSecs();
    if (nowEpoch >= lastPositionHeartbeatEpoch && nowEpoch - lastPositionHeartbeatEpoch >= heartbeatSecs) {
        if (!sendFreshPosition(false))
            sendBestPosition(false);
        lastPositionHeartbeatEpoch = nowEpoch;
        LOG_INFO("Tracker V1.1: TAK light-sleep heartbeat sent after %us", (unsigned)heartbeatSecs);
    }
}

class TrackerCommonSleepObserver : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!trackerRoleEnabled())
            return 0;
        return (serviceActive || motionActive || motionCandidatePending || finalPositionWaitStartedMs != 0) ? 1 : 0;
    }
};

TrackerCommonSleepObserver commonSleepObserver;
bool sleepObserverInstalled = false;

class TrackerCommonThread : public concurrency::OSThread
{
  public:
    TrackerCommonThread() : concurrency::OSThread("TrackerCommon") {}

  protected:
    int32_t runOnce() override
    {
        if (!trackerRoleEnabled())
            return 30000;

        const uint32_t now = millis();

        if (!bootHandoffComplete && graphics::isBootScreenComplete()) {
            bootHandoffComplete = true;
            LOG_INFO("Tracker V1.1: Meshtastic boot screen complete; native tracker page available");
            if (serviceActive)
                showTrackerScreen();
            else if (screen && screen->isScreenOn())
                screen->setOn(false);
        }

        processMotion(now);
        processBleActivity(now);
        rememberCurrentPosition();

        const gpio_num_t button = serviceButtonPin();
        const bool pressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;
        if (pressed) {
            buttonHighSinceMs = 0;
            if (!buttonWasPressed) {
                buttonWasPressed = true;
                buttonPressedSinceMs = now ? now : 1;
                openedServiceThisPress = false;

                if (!serviceActive) {
                    startService();
                    openedServiceThisPress = true;
                } else {
                    serviceLastActivityMs = now;
                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {
                        showTrackerScreen();
                        openedServiceThisPress = true;
                    }
                }
            }
        } else if (buttonWasPressed) {
            if (buttonHighSinceMs == 0)
                buttonHighSinceMs = now ? now : 1;
            if ((uint32_t)(now - buttonHighSinceMs) >= 25U) {
                if (serviceActive && !openedServiceThisPress) {
                    serviceLastActivityMs = now;
                    displayStartedMs = now ? now : 1;
                    displayVisible = true;
                    if (bootHandoffComplete && screen) {
                        screen->showNextFrame();
                        screen->runNow();
                    }
                }
                buttonWasPressed = false;
                openedServiceThisPress = false;
                buttonPressedSinceMs = 0;
                buttonHighSinceMs = 0;
            }
        } else {
            buttonHighSinceMs = 0;
        }

        if (serviceActive) {
            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= TRACKER_COMMON_SERVICE_MAX_MS;
            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= TRACKER_COMMON_SERVICE_IDLE_MS;
            if (hardCap || idle) {
                stopService();
            } else if (displayVisible && displayStartedMs != 0 &&
                       (uint32_t)(now - displayStartedMs) >= displayWindowMs) {
                closeDisplay();
                LOG_DEBUG("Tracker service: display window closed; Bluetooth service continues");
            }
        } else {
            bluetoothOff();
        }

        if (motionActive)
            processStationaryFinalPosition(now);
        else if (trackerUsesDeepSleep() && esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER)
            processDeepSleepTimerCycle(now);
        else
            processColdBootParking(now);

        updateLightSleepHeartbeat();
        return bootHandoffComplete ? 10 : 20;
    }
};

TrackerCommonThread *commonThread = nullptr;
} // namespace

bool trackerCommonScreenPowerAllowed(bool on)
{
    if (!trackerRoleEnabled() || !bootHandoffComplete)
        return true;
    return on == displayWindowActive();
}

void trackerCommonBleActivity()
{
    if (trackerRoleEnabled())
        rawBleActivitySequence.fetch_add(1);
}

void setupTrackerCommonPolicy()
{
    if (!trackerRoleEnabled() || commonThread)
        return;

    trackerServiceSettingsInit();
    setupTrackerEnhancements();
    setupVehicleAdaptiveGnss();

    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    trackerApplyPositionSettings();

    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = trackerEffectiveParkIntervalSecs();
    config.power.wait_bluetooth_secs = 1;
    config.network.wifi_enabled = false;

    bootActivityMs = millis();
    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
    processedMotionEdgeSequence = motionEdgeSequence;
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);
    gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);

    const gpio_num_t button = serviceButtonPin();
    if (button != GPIO_NUM_NC) {
        pinMode(button, INPUT_PULLUP);
        gpio_wakeup_enable(button, GPIO_INTR_LOW_LEVEL);
    }

    if (!sleepObserverInstalled) {
        commonSleepObserver.observe(&preflightSleep);
        sleepObserverInstalled = true;
    }

    // Preserve the last deep-sleep position for the native page and as a
    // fallback while a new GNSS fix is still pending.
    if (trackerUsesDeepSleep() && retainedLastPositionValid)
        restoreRetainedPosition();

    bluetoothOff();
    trackerStatusSetMotionActive(false);

    if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0) {
        motionCandidateCount = 1;
        motionCandidateStartedMs = millis() ? millis() : 1;
        motionCandidatePending = true;
        parked = false;
        LOG_INFO("Tracker V1.1: GPIO%d motion wake candidate (1/%u)", VEHICLE_MOTION_WAKE_PIN,
                 (unsigned)trackerMotionConfirmCount());
    }

    commonThread = new TrackerCommonThread();

    if (bootWasUserWake()) {
        startService();
        openedServiceThisPress = true;
        buttonWasPressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;
        buttonPressedSinceMs = millis();
    }

    LOG_INFO("Tracker V1.1 shared policy enabled: TAK=light sleep, TAK_TRACKER=deep sleep; motion/GNSS/UI/BLE behavior shared");
}

#else

bool trackerCommonScreenPowerAllowed(bool) { return true; }
void trackerCommonBleActivity() {}
void setupTrackerCommonPolicy() {}

#endif
