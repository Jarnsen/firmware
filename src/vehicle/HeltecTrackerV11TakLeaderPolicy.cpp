#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && !MESHTASTIC_EXCLUDE_GPS

#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "concurrency/OSThread.h"
#include "graphics/Screen.h"
#include "main.h"
#include "target_specific.h"

#include <cstdio>

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

static bool leaderServiceActive = false;
static uint32_t leaderServiceStartedMs = 0;
static uint32_t leaderLastKeepaliveMs = 0;
static uint32_t leaderDisplayStartedMs = 0;
static uint32_t leaderDisplayWindowMs = TAK_LEADER_DISPLAY_MS;
static bool leaderButtonLatched = false;
static uint32_t leaderButtonLowSinceMs = 0;
static char leaderBanner[128];

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

    // Ensure PowerFSM is in a user-active state while the intentional ATAK
    // service window is running.
    powerFSM.trigger(EVENT_PRESS);
    LOG_INFO("TAK leader: 120s ATAK/Bluetooth service window started");
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
                // Refresh ON state more frequently than the unattended 1-second
                // Bluetooth timeout so an intentional ATAK session cannot fall
                // back into light sleep between phone packets.
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
        } else {
            // A TAK leadership node must receive LoRa continuously but does not need
            // BLE merely because a packet arrived for a phone that is currently off.
            // PowerFSM's Bluetooth wait is reduced to 1s below; this additional gate
            // turns BLE back off at the next scheduler opportunity.
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

    // TAK leadership nodes should stay in normal ESP32 light sleep, never the
    // custom parked deep-sleep vehicle profile. GPS and LoRa remain available.
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = 3600;

    // WiFi prevents the normal power-saving transition and is not required for
    // the ATAK-over-Bluetooth field workflow.
    config.network.wifi_enabled = false;

    // When no phone is intentionally active, a received packet may briefly put
    // PowerFSM into DARK. One second is enough to process it before returning to
    // light sleep; the GPIO0 service policy keeps the node awake for 120s when needed.
    config.power.wait_bluetooth_secs = 1;

    const gpio_num_t button = takLeaderButtonPin();
    if (button != GPIO_NUM_NC)
        pinMode(button, INPUT_PULLUP);

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("TAK leader profile: GNSS + LoRa active, light sleep enabled, BLE on demand via GPIO0");
    takLeaderPolicyThread = new HeltecTrackerV11TakLeaderPolicyThread();
}

#endif // HELTEC_TRACKER_V1_1 && GPS
