#include "TrackerVariantPolicy.h"

#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "TrackerCommonPolicy.h"
#include "main.h"

extern "C" bool meshtasticTrackerScreenPowerAllowed(bool on)
{
    return trackerCommonScreenPowerAllowed(on);
}

extern "C" void meshtasticTrackerBleActivity()
{
    trackerCommonBleActivity();
}

static bool repairLegacyTrackerButtonConfig()
{
    if (config.device.button_gpio == 0)
        return false;

    const uint8_t oldPin = config.device.button_gpio;
    config.device.button_gpio = 0;
    if (nodeDB)
        nodeDB->saveToDisk(SEGMENT_CONFIG);

    LOG_WARN("Tracker V1.1: repaired persisted button_gpio=%u -> GPIO0; rebooting once to rebind InputBroker safely",
             (unsigned)oldPin);
    return true;
}

#endif

void setupJarnsenTrackerVariantPolicy()
{
#if defined(HELTEC_TRACKER_V1_1)
    const bool customRole = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
                            config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
    if (!customRole)
        return;

    config.display.screen_on_secs = 20;

#if defined(VEHICLE_MOTION_WAKE_PIN)
    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
#endif

    if (repairLegacyTrackerButtonConfig()) {
        rebootAtMsec = millis() + 1500UL;
        return;
    }

    // TAK and TAK_TRACKER intentionally use one runtime policy. Their only
    // operational difference is the parked sleep depth selected inside it.
    setupTrackerCommonPolicy();
#endif
}
