#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "JarnsenBuildInfo.h"
#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "TrackerEnhancements.h"
#include "TrackerServiceSettings.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "main.h"
#include "modules/PositionModule.h"
#include "sleep.h"
#include "target_specific.h"

#include <cstdio>
#include <driver/gpio.h>

#ifndef TAK_LEADER_SERVICE_MS
#define TAK_LEADER_SERVICE_MS (120UL * 1000UL)
#endif

#ifndef TAK_LEADER_SERVICE_MAX_MS
#define TAK_LEADER_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif

#ifndef TAK_LEADER_DISPLAY_MS
#define TAK_LEADER_DISPLAY_MS 20000UL
#endif

#ifndef TAK_LEADER_LOW_BATTERY_DISPLAY_MS
#define TAK_LEADER_LOW_BATTERY_DISPLAY_MS 10000UL
#endif

#ifndef TAK_LEADER_LOW_BATTERY_PERCENT
#define TAK_LEADER_LOW_BATTERY_PERCENT 20U
#endif

#ifndef TAK_LEADER_MOTION_QUIET_MS
#define TAK_LEADER_MOTION_QUIET_MS (120UL * 1000UL)
#endif

#ifndef TAK_LEADER_MOTION_STUCK_LOW_MS
#define TAK_LEADER_MOTION_STUCK_LOW_MS 30000UL
#endif

#ifndef TAK_LEADER_MENU_LONG_PRESS_MS
#define TAK_LEADER_MENU_LONG_PRESS_MS 1200UL
#endif

enum TakLeaderServicePage : uint8_t {
    TAK_PAGE_STATUS = 0,
    TAK_PAGE_DIAG,
    TAK_PAGE_VERSION,
    TAK_PAGE_MOTION,
    TAK_PAGE_DISTANCE,
    TAK_PAGE_INTERVAL,
    TAK_PAGE_PARK,
    TAK_PAGE_COUNT,
};

static bool leaderServiceActive = false;
static uint32_t leaderServiceStartedMs = 0;
static uint32_t leaderServiceLastActivityMs = 0;
static uint32_t leaderDisplayStartedMs = 0;
static uint32_t leaderDisplayWindowMs = TAK_LEADER_DISPLAY_MS;
static bool leaderButtonLatched = false;
static bool leaderOpenedServiceThisPress = false;
static bool leaderLongPressHandled = false;
static uint32_t leaderButtonLowSinceMs = 0;
static uint8_t leaderServicePage = TAK_PAGE_STATUS;
static char leaderBanner[160];

static volatile uint32_t leaderMotionEdgeSequence = 0;
static uint32_t leaderProcessedMotionEdgeSequence = 0;
static uint8_t leaderMotionCandidateCount = 0;
static uint32_t leaderMotionCandidateStartedMs = 0;
static bool leaderMotionCandidatePending = false;
static bool leaderMotionActive = false;
static uint32_t leaderLastMotionMs = 0;
static bool leaderMotionLevelWasLow = false;
static uint32_t leaderMotionPinLowSinceMs = 0;
static bool leaderMotionWakeDisabledForStuckLow = false;
static uint32_t leaderLastPositionHeartbeatEpoch = 0;

static bool takLeaderEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK;
}

static gpio_num_t takLeaderButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);
#else
    return GPIO_NUM_NC;
#endif
}

static bool takLeaderLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;

    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= TAK_LEADER_LOW_BATTERY_PERCENT;
}

static bool takLeaderBleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

static unsigned takLeaderDisplayAge(uint32_t age)
{
    return age == UINT32_MAX ? 9999U : (unsigned)age;
}

static unsigned takLeaderHeartbeatAgeSecs()
{
    if (leaderLastPositionHeartbeatEpoch == 0)
        return 9999U;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0 || nowEpoch < leaderLastPositionHeartbeatEpoch)
        return 9999U;
    return (unsigned)(nowEpoch - leaderLastPositionHeartbeatEpoch);
}

static void IRAM_ATTR takLeaderMotionISR()
{
    leaderMotionEdgeSequence++;
}

static void renderTakLeaderServicePage()
{
    if (!screen || !leaderServiceActive)
        return;

    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();

    const bool positionKnown = nodeDB && nodeDB->hasLocalPositionSinceBoot();

    switch ((TakLeaderServicePage)leaderServicePage) {
    case TAK_PAGE_STATUS:
        snprintf(leaderBanner, sizeof(leaderBanner), "TAK SERVICE\nBAT %u%% GPS %s\nBT ON  SHORT>NEXT", battery,
                 positionKnown ? "FIX" : "WAIT");
        break;
    case TAK_PAGE_DIAG:
        snprintf(leaderBanner, sizeof(leaderBanner), "DIAG GPS %s\nFIX %us HB %us\nSENSOR %s", positionKnown ? "FIX" : "WAIT",
                 takLeaderDisplayAge(trackerLastFixAgeSecs()), takLeaderHeartbeatAgeSecs(), trackerMotionSensorStatus());
        break;
    case TAK_PAGE_VERSION:
        snprintf(leaderBanner, sizeof(leaderBanner), "%s\nBUILD %.8s\nUP %umin %s", JARNSEN_FIRMWARE_VERSION,
                 JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL), trackerBootWakeReason());
        break;
    case TAK_PAGE_MOTION:
        snprintf(leaderBanner, sizeof(leaderBanner), "MOTION %s\n%u PULSES / %us\nLONG=CHANGE",
                 trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
                 (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));
        break;
    case TAK_PAGE_DISTANCE:
        snprintf(leaderBanner, sizeof(leaderBanner), "MIN DISTANCE\n%u m\nLONG=CHANGE", (unsigned)trackerSmartDistanceM());
        break;
    case TAK_PAGE_INTERVAL:
        snprintf(leaderBanner, sizeof(leaderBanner), "MIN INTERVAL\n%u s\nLONG=CHANGE", (unsigned)trackerSmartIntervalSecs());
        break;
    case TAK_PAGE_PARK:
        snprintf(leaderBanner, sizeof(leaderBanner), "HEARTBEAT\n%u min / eff %us\nLONG=CHANGE",
                 (unsigned)trackerParkIntervalMinutes(), (unsigned)trackerEffectiveParkIntervalSecs());
        break;
    default:
        leaderServicePage = TAK_PAGE_STATUS;
        renderTakLeaderServicePage();
        return;
    }

    leaderDisplayStartedMs = millis();
    leaderDisplayWindowMs = takLeaderLowBattery() ? TAK_LEADER_LOW_BATTERY_DISPLAY_MS : TAK_LEADER_DISPLAY_MS;
    screen->setOn(true);
    screen->showSimpleBanner(leaderBanner, leaderDisplayWindowMs);
}

static void changeTakLeaderServiceSetting()
{
    switch ((TakLeaderServicePage)leaderServicePage) {
    case TAK_PAGE_MOTION:
        trackerCycleMotionSensitivity();
        break;
    case TAK_PAGE_DISTANCE:
        trackerCycleSmartDistance();
        break;
    case TAK_PAGE_INTERVAL:
        trackerCycleSmartInterval();
        break;
    case TAK_PAGE_PARK:
        trackerCycleParkInterval();
        config.power.ls_secs = trackerEffectiveParkIntervalSecs();
        break;
    default:
        return;
    }

    renderTakLeaderServicePage();
}

static void startTakLeaderService()
{
    const uint32_t now = millis();
    leaderServiceActive = true;
    leaderServiceStartedMs = now;
    leaderServiceLastActivityMs = now;
    leaderServicePage = TAK_PAGE_STATUS;

    if (config.bluetooth.enabled)
        setBluetoothEnable(true);
    else
        LOG_WARN("TAK leader: Bluetooth is disabled in saved config; enable it once so GPIO0 service can start BLE");

    renderTakLeaderServicePage();

    // Wake the normal PowerFSM once. If it later reaches the light-sleep state,
    // the dedicated sleep-veto observer below keeps the CPU running for the
    // intentional ATAK/service window.
    powerFSM.trigger(EVENT_PRESS);
    LOG_INFO("TAK leader: GPIO0 opened ATAK/Bluetooth/settings; %us idle timeout, %us hard cap",
             (unsigned)(TAK_LEADER_SERVICE_MS / 1000UL), (unsigned)(TAK_LEADER_SERVICE_MAX_MS / 1000UL));
}

static bool takLeaderServiceStillActive(uint32_t now)
{
    if (!leaderServiceActive)
        return false;

    const bool belowHardCap = (uint32_t)(now - leaderServiceStartedMs) < (uint32_t)TAK_LEADER_SERVICE_MAX_MS;
    const bool belowIdleTimeout = (uint32_t)(now - leaderServiceLastActivityMs) < (uint32_t)TAK_LEADER_SERVICE_MS;
    return belowHardCap && belowIdleTimeout;
}

static void updateTakLeaderMotionWakeHealth(uint32_t now)
{
    const gpio_num_t motionPin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;
    const bool low = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;

    if (low) {
        if (leaderMotionPinLowSinceMs == 0) {
            leaderMotionPinLowSinceMs = now ? now : 1;
        } else if (!leaderMotionWakeDisabledForStuckLow &&
                   (uint32_t)(now - leaderMotionPinLowSinceMs) >= TAK_LEADER_MOTION_STUCK_LOW_MS) {
            leaderMotionWakeDisabledForStuckLow = true;
            gpio_wakeup_disable(motionPin);
            LOG_WARN("TAK leader: GPIO%d LOW for %us; light-sleep motion wake temporarily disabled",
                     VEHICLE_MOTION_WAKE_PIN, (unsigned)(TAK_LEADER_MOTION_STUCK_LOW_MS / 1000UL));
        }
    } else {
        leaderMotionPinLowSinceMs = 0;
        if (leaderMotionWakeDisabledForStuckLow) {
            leaderMotionWakeDisabledForStuckLow = false;
            gpio_wakeup_enable(motionPin, GPIO_INTR_LOW_LEVEL);
            LOG_INFO("TAK leader: GPIO%d recovered HIGH; light-sleep motion wake restored", VEHICLE_MOTION_WAKE_PIN);
        }
    }
}

static void confirmTakLeaderMotion(uint32_t now)
{
    leaderMotionActive = true;
    leaderLastMotionMs = now;
    leaderMotionCandidateCount = 0;
    leaderMotionCandidateStartedMs = 0;
    leaderMotionCandidatePending = false;
    LOG_INFO("TAK leader: movement confirmed (%u pulses within %ums)", (unsigned)trackerMotionConfirmCount(),
             (unsigned)trackerMotionConfirmWindowMs());
}

static void processTakLeaderMotion(uint32_t now)
{
    const bool pinLow = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;
    const uint32_t currentSequence = leaderMotionEdgeSequence;
    uint32_t newEdges = currentSequence - leaderProcessedMotionEdgeSequence;

    // GPIO wake from light sleep can occur before the regular Arduino ISR gets
    // CPU time. Count a newly-observed LOW level as the first candidate pulse if
    // the ISR did not already report that same transition.
    if (newEdges == 0 && pinLow && !leaderMotionLevelWasLow)
        newEdges = 1;

    leaderProcessedMotionEdgeSequence = currentSequence;
    leaderMotionLevelWasLow = pinLow;

    if (newEdges != 0) {
        if (leaderMotionActive) {
            leaderLastMotionMs = now;
        } else {
            const uint32_t confirmWindowMs = trackerMotionConfirmWindowMs();
            if (!leaderMotionCandidatePending ||
                (uint32_t)(now - leaderMotionCandidateStartedMs) > confirmWindowMs) {
                leaderMotionCandidateCount = 0;
                leaderMotionCandidateStartedMs = now;
                leaderMotionCandidatePending = true;
            }

            const uint8_t confirmCount = trackerMotionConfirmCount();
            const uint32_t needed = confirmCount > leaderMotionCandidateCount
                                        ? (uint32_t)confirmCount - leaderMotionCandidateCount
                                        : 0U;
            const uint32_t accepted = newEdges < needed ? newEdges : needed;
            leaderMotionCandidateCount = (uint8_t)(leaderMotionCandidateCount + accepted);
            if (leaderMotionCandidateCount >= confirmCount)
                confirmTakLeaderMotion(now);
        }
    }

    if (leaderMotionCandidatePending &&
        (uint32_t)(now - leaderMotionCandidateStartedMs) >= trackerMotionConfirmWindowMs()) {
        LOG_DEBUG("TAK leader: rejected vibration candidate (%u/%u pulses)", (unsigned)leaderMotionCandidateCount,
                  (unsigned)trackerMotionConfirmCount());
        leaderMotionCandidateCount = 0;
        leaderMotionCandidateStartedMs = 0;
        leaderMotionCandidatePending = false;
    }

    if (leaderMotionActive && (uint32_t)(now - leaderLastMotionMs) >= TAK_LEADER_MOTION_QUIET_MS) {
        leaderMotionActive = false;
        LOG_INFO("TAK leader: 120s motion quiet; returning to always-listening light sleep");
    }

    updateTakLeaderMotionWakeHealth(now);
}

static void updateTakLeaderPositionHeartbeat()
{
    if (!positionModule || !nodeDB || !nodeDB->hasLocalPositionSinceBoot())
        return;

    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (nowEpoch == 0)
        return;

    if (leaderLastPositionHeartbeatEpoch == 0) {
        // PositionModule handles the initial fresh-position broadcast itself.
        leaderLastPositionHeartbeatEpoch = nowEpoch;
        return;
    }

    const uint32_t heartbeatSecs = trackerEffectiveParkIntervalSecs();
    if (nowEpoch >= leaderLastPositionHeartbeatEpoch &&
        (nowEpoch - leaderLastPositionHeartbeatEpoch) >= heartbeatSecs) {
        positionModule->sendOurPosition();
        leaderLastPositionHeartbeatEpoch = nowEpoch;
        LOG_INFO("TAK leader: autonomous position heartbeat sent after %us", (unsigned)heartbeatSecs);
    }
}

class TakLeaderSleepVeto : public Observer<void *>
{
  protected:
    int onNotify(void *deepSleepMarker) override
    {
        if (!takLeaderEnabled())
            return 0;

        // Never block a true deep sleep/shutdown request (for example critical
        // battery protection). The non-null marker is used by sleep.cpp only
        // for hardware-power-down sleep.
        if (deepSleepMarker != nullptr)
            return 0;

        // During movement confirmation, confirmed driving, or an intentional
        // ATAK/service window we need the scheduler/GNSS parser to keep running.
        return (leaderServiceActive || leaderMotionActive || leaderMotionCandidatePending) ? 1 : 0;
    }
};

class HeltecTrackerV11TakLeaderPolicyThread : public concurrency::OSThread
{
  public:
    HeltecTrackerV11TakLeaderPolicyThread() : concurrency::OSThread("TakLeaderPolicy") {}

  protected:
    int32_t runOnce() override
    {
        if (!takLeaderEnabled())
            return 30000;

        const uint32_t now = millis();
        processTakLeaderMotion(now);
        updateTakLeaderPositionHeartbeat();

        const gpio_num_t button = takLeaderButtonPin();
        if (button != GPIO_NUM_NC) {
            const bool pressed = digitalRead(button) == LOW;

            if (pressed) {
                if (leaderButtonLowSinceMs == 0)
                    leaderButtonLowSinceMs = now ? now : 1;

                if (!leaderButtonLatched && (uint32_t)(now - leaderButtonLowSinceMs) >= 80U) {
                    leaderButtonLatched = true;
                    leaderOpenedServiceThisPress = false;
                    leaderLongPressHandled = false;

                    if (!leaderServiceActive) {
                        startTakLeaderService();
                        leaderOpenedServiceThisPress = true;
                    }
                }

                if (leaderButtonLatched && leaderServiceActive && !leaderOpenedServiceThisPress && !leaderLongPressHandled &&
                    (uint32_t)(now - leaderButtonLowSinceMs) >= (uint32_t)TAK_LEADER_MENU_LONG_PRESS_MS) {
                    changeTakLeaderServiceSetting();
                    leaderLongPressHandled = true;
                }
            } else {
                if (leaderButtonLatched && leaderServiceActive && !leaderOpenedServiceThisPress && !leaderLongPressHandled) {
                    leaderServicePage = (uint8_t)((leaderServicePage + 1U) % TAK_PAGE_COUNT);
                    renderTakLeaderServicePage();
                }

                leaderButtonLatched = false;
                leaderOpenedServiceThisPress = false;
                leaderLongPressHandled = false;
                leaderButtonLowSinceMs = 0;
            }
        }

        // Keep the two-minute timeout rolling while ATAK/Meshtastic has a live
        // BLE connection. A 15-minute hard cap protects the battery if a phone
        // remains paired accidentally.
        if (leaderServiceActive && takLeaderBleConnected())
            leaderServiceLastActivityMs = now;

        if (leaderServiceActive) {
            if (!takLeaderServiceStillActive(now)) {
                leaderServiceActive = false;
                setBluetoothEnable(false);
                if (screen)
                    screen->setOn(false);
                LOG_INFO("TAK leader: ATAK/Bluetooth/settings window complete");
            } else {
                // Sleep is vetoed by TakLeaderSleepVeto while service is active.
                if (config.bluetooth.enabled)
                    setBluetoothEnable(true);

                if (screen) {
                    if ((uint32_t)(now - leaderDisplayStartedMs) < leaderDisplayWindowMs)
                        screen->setOn(true);
                    else
                        screen->setOn(false);
                }
            }
        } else if (leaderMotionActive || leaderMotionCandidatePending) {
            // The sleep veto keeps the CPU/GNSS parser alive for Smart Position;
            // movement alone must not waste power on BLE or the display.
            setBluetoothEnable(false);
            if (screen)
                screen->setOn(false);
        } else {
            // Stationary leadership mode: LoRa remains listening in light sleep;
            // BLE/display stay off unless GPIO0 intentionally opens service.
            setBluetoothEnable(false);
            if (screen)
                screen->setOn(false);
        }

        return 100;
    }
};

static HeltecTrackerV11TakLeaderPolicyThread *takLeaderPolicyThread = nullptr;
static TakLeaderSleepVeto *takLeaderSleepVeto = nullptr;

void setupHeltecTrackerV11TakLeaderPolicy()
{
    if (!takLeaderEnabled() || takLeaderPolicyThread != nullptr)
        return;

    trackerServiceSettingsInit();

    // Leadership position policy: autonomous GNSS reporting remains available
    // even with the ATAK phone powered off. These values come from the local
    // persisted service settings and can be changed with GPIO0.
    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    trackerApplyPositionSettings();

    // Avoid accidental field toggles and unnecessary status LED consumption.
    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;

    // TAK leadership nodes use normal ESP32 light sleep, never the custom parked
    // deep-sleep vehicle profile. LoRa and GPS stay on during light sleep.
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = trackerEffectiveParkIntervalSecs();

    // WiFi prevents the normal power-saving transition and is not required for
    // the ATAK-over-Bluetooth field workflow.
    config.network.wifi_enabled = false;

    // Unattended packet wakes should not hold BLE up for a phone that is off.
    config.power.wait_bluetooth_secs = 1;

    const gpio_num_t button = takLeaderButtonPin();
    if (button != GPIO_NUM_NC)
        pinMode(button, INPUT_PULLUP);

    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT); // external 100 kOhm pull-up
    leaderProcessedMotionEdgeSequence = leaderMotionEdgeSequence;
    leaderMotionLevelWasLow = digitalRead(VEHICLE_MOTION_WAKE_PIN) == LOW;
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);
    gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);

    takLeaderSleepVeto = new TakLeaderSleepVeto();
    takLeaderSleepVeto->observe(&preflightSleep);

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("TAK leader profile: GNSS + LoRa light sleep, jittered heartbeat, diagnostics, BLE/settings on demand via GPIO0");
    takLeaderPolicyThread = new HeltecTrackerV11TakLeaderPolicyThread();
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN && GPS
