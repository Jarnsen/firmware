#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "graphics/Screen.h"
#include "main.h"
#include "target_specific.h"

// Heltec V3 repeater policy.
//
// This deliberately uses Meshtastic's normal ESP32 light-sleep path instead of
// deep sleep. LoRa/SX1262 therefore remains available as a wake source while
// the ESP32-S3, display and client radios spend as much time as possible asleep.
// The policy is only applied when the saved device role is REPEATER.
void lateInitVariant()
{
    if (config.device.role != meshtastic_Config_DeviceConfig_Role_REPEATER) {
        LOG_INFO("Heltec V3 repeater policy inactive (role=%d); set role REPEATER to enable", (int)config.device.role);
        return;
    }

    // Repeater is infrastructure-only: avoid client-radio and display wakeups.
    config.bluetooth.enabled = false;
    config.network.wifi_enabled = false;
    config.display.screen_on_secs = 1;

    // Force the normal ESP32 power FSM to use light sleep. A one-second minimum
    // wake window is enough to service a radio IRQ before returning to sleep.
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;

    // Keep long light-sleep stretches; LoRa IRQ can still wake immediately.
    // This only reduces periodic timer/service wake overhead.
    config.power.ls_secs = 3600;

    // A pure repeater does not need to decode application payloads before
    // rebroadcasting them. This is both the lowest-overhead and least chatty
    // rebroadcast mode permitted for REPEATER.
    config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL_SKIP_DECODING;

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    LOG_INFO("Heltec V3 REPEATER: light sleep enabled, LoRa wake active, BLE/WiFi/display disabled");
}

#endif // _VARIANT_HELTEC_V3
