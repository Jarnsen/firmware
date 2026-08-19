#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "graphics/Screen.h"
#include "main.h"
#include "target_specific.h"

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

    // Infrastructure-only operation: client radios and display should not burn
    // power while the node waits for LoRa traffic.
    config.bluetooth.enabled = false;
    config.network.wifi_enabled = false;
    config.display.screen_on_secs = 1;

    // Use Meshtastic's ESP32 light-sleep path. LoRa IRQ remains able to wake the
    // processor immediately. Keep the post-wake processing window short.
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;

    // Long LS timer intervals reduce periodic service wake overhead; LoRa IRQ
    // is independent of this timer and still wakes immediately.
    config.power.ls_secs = 3600;

    if (legacyRepeater) {
        // Only the legacy REPEATER role permits skip-decoding rebroadcast mode.
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL_SKIP_DECODING;
    }

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("Heltec V3 %s duty: light sleep enabled, LoRa wake active, BLE/WiFi/display disabled",
             routerLate ? "ROUTER_LATE repeater" : "legacy REPEATER");
}

#endif // _VARIANT_HELTEC_V3
