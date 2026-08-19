#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "main.h"
#include "modules/PositionModule.h"
#include "target_specific.h"

#include <cstdio>
#include <driver/gpio.h>

#ifndef TAK_LEADER_SERVICE_MS
#define TAK_LEADER_SERVICE_MS (120UL * 1000UL)
#endif

#ifndef TAK_LEADER_KEEPALIVE_MS
#define TAK_LEADER_KEEPALIVE_MS 500UL
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

#ifndef TAK_LEADER_MOTION_CONFIRM_COUNT
#define TAK_LEADER_MOTION_CONFIRM_COUNT 3U
#endif

#ifndef TAK_LEADER_MOTION_CONFIRM_WINDOW_MS
#define TAK_LEADER_MOTION_CONFIRM_WINDOW_MS 3000UL
#endif

#ifndef TAK_LEADER_MOTION_QUIET_MS
#define TAK_LEADER_MOTION_QUIET_MS (120UL * 1000UL)
#endif

#ifndef TAK_LEADER_MOTION_STUCK_LOW_MS
#define TAK_LEADER_MOTION_STUCK_LOW_MS 30000UL
#endif

#ifndef TAK_LEADER_POSITION_HEARTBEAT_SECS
#define TAK_LEADER_POSITION_HEARTBEAT_SECS 3600UL
#endif

static bool leaderServiceActive = false;
static uint32_t leaderServiceStartedMs = 0;
static uint32_t leaderLastKeepaliveMs = 0;
static uint32_t leaderDisplayStartedMs = 0;
static uint32_t leaderDisplayWindowMs = TAK_LEADER_DISPLAY_MS;
static bool leaderButtonLatched = false;
static uint32_t leaderButtonLowSinceMs = 0;
static char leaderBanner[128];

static volatile uint32_t leaderMotionEdgeSequence = 0;
static uint32_t leaderProcessedMotionEdgeSequence = 0;
static uint8_t leaderMotionCandidateCount = 0;
static uint32_t leaderMotionCandidateStartedMs = 0;
static bool leaderMotionCandidatePending = false;
static bool leaderMotionActive = false;
static uint32_t leaderLastMotionMs = 0;
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

static void IRAM_ATTR takLeaderMotionISR()
{
    leaderMotionEdgeSequence++;
}

static void updateTakLeaderBanner()
{
    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();

    const bool positionKnown = nodeDB && nodeDB->hasLocalPositionSinceBoot();
    snprintf(leaderBanner, sizeof(leaderBanner), "TAK LEADER\nBAT %u%%  GPS %s\nBT SERVICE 120s", battery,
             positionKnown ? "READY" : "WAIT");
}

static void startTakLeaderService()
{
    const uint32_t now = millis();
    leaderServiceActive = true;
    leaderServiceStartedMs = now;
    leaderLastKeepaliveMs = now;
    leaderDisplayStartedMs = now;
    leaderDisplayWindowMs = takLeaderLowBattery() ? TAK_LEADER_LOW_BATTERY_DISPLAY_MS : TAK_LEADER_DISPLAY_MS;

    if (config.bluetooth.enabled)
        setBluetoothEnable(true);
    else
        LOG_WARN("TAK leader: Bluetooth is disabled in saved config; enable it once so GPIO0 service can start BLE");

    if (screen) {
        updateTakLeaderBanner();
        screen->setOn(true);
        screen->showSimpleBanner(leaderBanner, leaderDisplayWindowMs);
    }

    powerFSM.trigger(EVENT_PRESS);
    LOG_INFO("TAK leader: 120s ATAK/Bluetooth service window started");
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
    LOG_INFO("TAK leader: movement confirmed (%u pulses within %ums)", (unsigned)TAK_LEADER_MOTION_CONFIRM_COUNT,
             (unsigned)TAK_LEADER_MOTION_CONFIRM_WINDOW_MS);
}

static void processTakLeaderMotion(uint32_t now)
{
    const uint32_t currentSequence = leaderMotionEdgeSequence;
    const uint32_t newEdges = currentSequence - leaderProcessedMotionEdgeSequence;
    if (newEdges != 0) {
        leaderProcessedMotionEdgeSequence = currentSequence;

        if (leaderMotionActive) {
            leaderLastMotionMs = now;
        } else {
            if (!leaderMotionCandidatePending ||
                (uint32_t)(now - leaderMotionCandidateStartedMs) > TAK_LEADER_MOTION_CONFIRM_WINDOW_MS) {
                leaderMotionCandidateCount = 0;
                leaderMotionCandidateStartedMs = now;
                leaderMotionCandidatePending = true;
            }

            const uint32_t needed = TAK_LEADER_MOTION_CONFIRM_COUNT > leaderMotionCandidateCount
                                        ? (uint32_t)TAK_LEADER_MOTION_CONFIRM_COUNT - leaderMotionCandidateCount
                                        : 0U;
            const uint32_t accepted = newEdges < needed ? newEdges : needed;
            leaderMotionCandidateCount = (uint8_t)(leaderMotionCandidateCount + accepted);
            if (leaderMotionCandidateCount >= TAK_LEADER_MOTION_CONFIRM_COUNT)
                confirmTakLeaderMotion(now);
        }
    }

    if (leaderMotionCandidatePending &&
        (uint32_t)(now - leaderMotionCandidateStartedMs) >= TAK_LEADER_MOTION_CONFIRM_WINDOW_MS) {
        LOG_DEBUG("TAK leader: rejected vibration candidate (%u/%u pulses)", (unsigned)leaderMotionCandidateCount,
                  (unsigned)TAK_LEADER_MOTION_CONFIRM_COUNT);
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

    if (nowEpoch >= leaderLastPositionHeartbeatEpoch &&
        (nowEpoch - leaderLastPositionHeartbeatEpoch) >= TAK_LEADER_POSITION_HEARTBEAT_SECS) {
        positionModule->sendOurPosition();
        leaderLastPositionHeartbeatEpoch = nowEpoch;
        LOG_INFO("TAK leader: hourly autonomous position heartbeat sent");
    }
}

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
            if (pressed && !leaderButtonLatched) {
                if (leaderButtonLowSinceMs == 0)
                    leaderButtonLowSinceMs = now ? now : 1;
                else if ((uint32_t)(now - leaderButtonLowSinceMs) >= 80U) {
                    leaderButtonLatched = true;
                    startTakLeaderService();
                }
            } else if (!pressed) {
                leaderButtonLatched = false;
                leaderButtonLowSinceMs = 0;
            }
        }

        if (leaderServiceActive) {
            if ((uint32_t)(now - leaderServiceStartedMs) >= TAK_LEADER_SERVICE_MS) {
                leaderServiceActive = false;
                setBluetoothEnable(false);
                if (screen)
                    screen->setOn(false);
                LOG_INFO("TAK leader: ATAK/Bluetooth service window complete");
            } else {
                if ((uint32_t)(now - leaderLastKeepaliveMs) >= TAK_LEADER_KEEPALIVE_MS) {
                    powerFSM.trigger(EVENT_PRESS);
                    if (config.bluetooth.enabled)
                        setBluetoothEnable(true);
                    leaderLastKeepaliveMs = now;
                }

                if (screen) {
                    if ((uint32_t)(now - leaderDisplayStartedMs) < leaderDisplayWindowMs)
                        screen->setOn(true);
                    else
                        screen->setOn(false);
                }
            }
        } else if (leaderMotionActive || leaderMotionCandidatePending) {
            // During confirmed movement (or the short confirmation window) keep the
            // CPU awake so PositionModule can evaluate Smart Position normally.
            // Immediately undo ON-state client UI/radio side effects: leadership
            // tracking needs GNSS + LoRa here, not BLE or the display.
            if ((uint32_t)(now - leaderLastKeepaliveMs) >= TAK_LEADER_KEEPALIVE_MS) {
                powerFSM.trigger(EVENT_PRESS);
                leaderLastKeepaliveMs = now;
            }
            setBluetoothEnable(false);
            if (screen)
                screen->setOn(false);
        } else {
            // Stationary leadership mode: LoRa remains listening in light sleep;
            // BLE/display stay off unless GPIO0 intentionally opens ATAK service.
            setBluetoothEnable(false);
            if (screen)
                screen->setOn(false);
        }

        return 100;
    }
};

static HeltecTrackerV11TakLeaderPolicyThread *takLeaderPolicyThread = nullptr;

void setupHeltecTrackerV11TakLeaderPolicy()
{
    if (!takLeaderEnabled() || takLeaderPolicyThread != nullptr)
        return;

    // Leadership position policy: autonomous GNSS reporting remains available
    // even with the ATAK phone powered off.
    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    config.position.position_broadcast_secs = TAK_LEADER_POSITION_HEARTBEAT_SECS;
    config.position.position_broadcast_smart_enabled = true;
    config.position.broadcast_smart_minimum_distance = 75;
    config.position.broadcast_smart_minimum_interval_secs = 30;

    // Avoid accidental field toggles and unnecessary status LED consumption.
    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;

    // TAK leadership nodes use normal ESP32 light sleep, never the custom parked
    // deep-sleep vehicle profile. LoRa and GPS stay on during light sleep.
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = TAK_LEADER_POSITION_HEARTBEAT_SECS;

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
    attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), takLeaderMotionISR, FALLING);
    gpio_wakeup_enable((gpio_num_t)VEHICLE_MOTION_WAKE_PIN, GPIO_INTR_LOW_LEVEL);

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("TAK leader profile: GNSS + LoRa light sleep, motion-aware tracking, BLE on demand via GPIO0");
    takLeaderPolicyThread = new HeltecTrackerV11TakLeaderPolicyThread();
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN && GPS
