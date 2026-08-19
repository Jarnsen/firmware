#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "NodeDB.h"
#include "graphics/Screen.h"
#include "main.h"
#include "target_specific.h"

#include <esp_system.h>

static uint32_t repeaterHealthIntervalSecs()
{
    if (!nodeDB)
        return 3600UL;

    uint32_t x = nodeDB->getNodeNum();
    x ^= x >> 16;
    x *= 0x7feb352dU;
    x ^= x >> 15;
    return 3300UL + (x % 301U);
}

// Custom Heltec V3 infrastructure policy intentionally lives outside
// src/platform/extra_variants. Keeping lateInitVariant here avoids carrying a
// custom copy of the upstream board variant implementation.
void lateInitVariant()
{
    const bool routerLate = config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
    const bool legacyRepeater = config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;

    if (!routerLate && !legacyRepeater) {
        LOG_INFO("Heltec V3 repeater policy inactive (role=%d); use ROUTER_LATE (recommended) or REPEATER", (int)config.device.role);
        return;
    }

    config.bluetooth.enabled = false;
    config.network.wifi_enabled = false;
    config.display.screen_on_secs = 1;
    config.device.led_heartbeat_disabled = true;

    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = 3600;

    moduleConfig.telemetry.device_telemetry_enabled = true;
    moduleConfig.telemetry.device_update_interval = repeaterHealthIntervalSecs();

    if (legacyRepeater)
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL_SKIP_DECODING;

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("Heltec V3 %s duty: LS + LoRa wake, BLE/WiFi/display/LED off, health=%us, resetReason=%d",
             routerLate ? "ROUTER_LATE repeater" : "legacy REPEATER",
             (unsigned)moduleConfig.telemetry.device_update_interval, (int)esp_reset_reason());
}

#endif // _VARIANT_HELTEC_V3
