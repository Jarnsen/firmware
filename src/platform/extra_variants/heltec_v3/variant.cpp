#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "NodeDB.h"
#include "graphics/Screen.h"
#include "main.h"
#include "target_specific.h"

#include <esp_system.h>

static uint32_t repeaterHealthIntervalSecs()
{
    // Spread the two infrastructure nodes across roughly 55..60 minutes so
    // their health packets do not habitually collide after a common restart.
    if (!nodeDB)
        return 3600UL;

    uint32_t x = nodeDB->getNodeNum();
    x ^= x >> 16;
    x *= 0x7feb352dU;
    x ^= x >> 15;
    return 3300UL + (x % 301U);
}

// Heltec V3 infrastructure/repeater power policy.
//
// The preferred role is ROUTER_LATE because current Meshtastic marks the old
// REPEATER role deprecated. REPEATER remains supported for deliberate legacy
// use. Both profiles use ESP32 light sleep rather than deep sleep so SX1262
// stays available as a LoRa wake source.
void lateInitVariant()
{
    const bool routerLate = config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
    const bool legacyRepeater = config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;

    if (!routerLate && !legacyRepeater) {
        LOG_INFO("Heltec V3 repeater policy inactive (role=%d); use ROUTER_LATE (recommended) or REPEATER", (int)config.device.role);
        return;
    }

    // Infrastructure-only operation: client radios, display and heartbeat LED
    // should not burn power while the node waits for LoRa traffic.
    config.bluetooth.enabled = false;
    config.network.wifi_enabled = false;
    config.display.screen_on_secs = 1;
    config.device.led_heartbeat_disabled = true;

    // Use Meshtastic's ESP32 light-sleep path. LoRa IRQ remains able to wake the
    // processor immediately. Keep the post-wake processing window short.
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;

    // Long LS timer intervals reduce periodic service wake overhead; LoRa IRQ
    // is independent of this timer and still wakes immediately.
    config.power.ls_secs = 3600;

    // Built-in Meshtastic device telemetry already carries battery percentage,
    // battery voltage (when available), uptime, channel utilization and TX air
    // utilization. Enable it explicitly for infrastructure health and spread
    // reports over 55..60 minutes to avoid synchronized fleet bursts.
    moduleConfig.telemetry.device_telemetry_enabled = true;
    moduleConfig.telemetry.device_update_interval = repeaterHealthIntervalSecs();

    if (legacyRepeater) {
        // Only the legacy REPEATER role permits skip-decoding rebroadcast mode.
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL_SKIP_DECODING;
    }

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("Heltec V3 %s duty: LS + LoRa wake, BLE/WiFi/display/LED off, health=%us, resetReason=%d",
             routerLate ? "ROUTER_LATE repeater" : "legacy REPEATER",
             (unsigned)moduleConfig.telemetry.device_update_interval, (int)esp_reset_reason());
}

#endif // _VARIANT_HELTEC_V3
