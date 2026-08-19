#include "configuration.h"

#ifdef _VARIANT_HELTEC_WIRELESS_TRACKER

#include "GPS.h"
#include "GpioLogic.h"
#include "graphics/TFTDisplay.h"
#include "vehicle/TrackerServiceSettings.h"

#if defined(HELTEC_TRACKER_V1_1) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11TakLeaderPolicy();
#endif

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11VehicleMotionTracker();
void setupVehicleServicePolicy();
void setupVehicleAdaptiveGnss();
#endif

static void configureTakTrackerVehicleProfile()
{
    // Core field-tracker behavior. Bluetooth must remain saved enabled so ESP32
    // keeps the BLE stack available, but unattended wakes only keep it up for a
    // moment; GPIO0 deliberately opens the real service window.
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

// Heltec tracker specific init
void lateInitVariant()
{
    // LOG_DEBUG("Heltec tracker initVariant");

#ifndef MESHTASTIC_EXCLUDE_GPS
    GpioVirtPin *virtGpsEnable = gps ? gps->enablePin : new GpioVirtPin();
#else
    GpioVirtPin *virtGpsEnable = new GpioVirtPin();
#endif

#ifndef MESHTASTIC_EXCLUDE_SCREEN
    // On this board we are actually using the backlightEnable signal to already be controlling a physical enable to the
    // display controller. But we'd ALSO like that signal to drive a virtual GPIO.
    GpioVirtPin *virtScreenEnable = new GpioVirtPin();
    if (TFTDisplay::backlightEnable) {
        GpioPin *physScreenEnable = TFTDisplay::backlightEnable;
        GpioPin *splitter = new GpioSplitter(virtScreenEnable, physScreenEnable);
        TFTDisplay::backlightEnable = splitter;

        // Assume screen is initially powered
        splitter->set(true);
    }
#endif

#if defined(VEXT_ENABLE) && (!defined(MESHTASTIC_EXCLUDE_GPS) || !defined(MESHTASTIC_EXCLUDE_SCREEN))
    // If either the GPS or the screen is on, turn on the external power regulator
    GpioPin *hwEnable = new GpioHwPin(VEXT_ENABLE);
    new GpioBinaryTransformer(virtGpsEnable, virtScreenEnable, hwEnable, GpioBinaryTransformer::Or);
#endif

#if defined(HELTEC_TRACKER_V1_1)
    // The local field presets belong only to our two custom TAK roles. Ordinary
    // Tracker V1.1 roles keep their normal Meshtastic configuration untouched.
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
        config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER)
        trackerServiceSettingsInit();
#endif

#if defined(HELTEC_TRACKER_V1_1) && !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK) {
        // Leadership element: GNSS + always-listening LoRa with light sleep,
        // Bluetooth only during intentional GPIO0 ATAK service.
        setupHeltecTrackerV11TakLeaderPolicy();
    }
#endif

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER) {
        // Kfz tracker: SW-18010P motion wake + parked deep sleep + adaptive GNSS.
        configureTakTrackerVehicleProfile();
        setupVehicleAdaptiveGnss();
        setupHeltecTrackerV11VehicleMotionTracker();
        setupVehicleServicePolicy();
    }
#endif
}

#endif