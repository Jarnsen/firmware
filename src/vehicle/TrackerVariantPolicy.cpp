#include "TrackerVariantPolicy.h"

#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "TrackerEnhancements.h"
#include "TrackerServiceSettings.h"
#include "main.h"

#if !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11TakLeaderPolicy();
#endif

#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11VehicleMotionTracker();
void setupVehicleServicePolicy();
void setupVehicleAdaptiveGnss();
#endif

static bool repairLegacyTrackerButtonConfig()
{
    // GPIO0 is permanently reserved for the local service button in both TAK
    // profiles. Older development builds could leave another button_gpio in
    // persistent config (notably GPIO7, now reserved for the motion sensor).
    // InputBroker is initialized before lateInitVariant(), so variant.h keeps
    // that legacy input pulled up long enough for us to repair it safely here.
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

static void configureTakTrackerVehicleProfile()
{
    config.power.is_power_saving = true;
    config.power.wait_bluetooth_secs = 1;

    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    trackerApplyPositionSettings();

    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;

    config.network.wifi_enabled = false;
}

#endif

void setupJarnsenTrackerVariantPolicy()
{
#if defined(HELTEC_TRACKER_V1_1)
    const bool customRole = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
                            config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;

    if (!customRole)
        return;

#if defined(VEHICLE_MOTION_WAKE_PIN)
    // Safe for boards with or without the external SW-18010P/100 kOhm network.
    // Both TAK roles use GPIO7 for vehicle motion, never as the service button.
    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
#endif

    if (repairLegacyTrackerButtonConfig()) {
        rebootAtMsec = millis() + 1500UL;
        return;
    }

    trackerServiceSettingsInit();
    setupTrackerEnhancements();

#if !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK) {
        setupHeltecTrackerV11TakLeaderPolicy();
        return;
    }
#endif

#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER) {
        configureTakTrackerVehicleProfile();
        setupVehicleAdaptiveGnss();
        setupHeltecTrackerV11VehicleMotionTracker();
        setupVehicleServicePolicy();
    }
#endif
#endif
}
