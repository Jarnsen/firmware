#include "TrackerVariantPolicy.h"

#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "TrackerEnhancements.h"
#include "TrackerServiceSettings.h"

#if !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11TakLeaderPolicy();
#endif

#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11VehicleMotionTracker();
void setupVehicleServicePolicy();
void setupVehicleAdaptiveGnss();
#endif

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
