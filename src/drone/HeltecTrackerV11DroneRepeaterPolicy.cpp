#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

#include "GPS.h"
#include "NodeDB.h"
#include "concurrency/OSThread.h"
#include "main.h"
#include "modules/PositionModule.h"

#include <driver/gpio.h>

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#ifndef DRONE_SMART_DISTANCE_M
#define DRONE_SMART_DISTANCE_M 25U
#endif
#ifndef DRONE_SMART_INTERVAL_SECS
#define DRONE_SMART_INTERVAL_SECS 10U
#endif
#ifndef DRONE_GPS_UPDATE_SECS
#define DRONE_GPS_UPDATE_SECS 1U
#endif
#ifndef DRONE_GROUND_HEARTBEAT_SECS
#define DRONE_GROUND_HEARTBEAT_SECS 30U
#endif
#ifndef DRONE_BT_IDLE_MS
#define DRONE_BT_IDLE_MS (120UL * 1000UL)
#endif
#ifndef DRONE_BT_HARD_CAP_MS
#define DRONE_BT_HARD_CAP_MS (15UL * 60UL * 1000UL)
#endif

namespace {
volatile uint32_t pendingBleActivityMs = 0;
bool serviceActive = false;
bool buttonWasPressed = false;
uint32_t serviceStartedMs = 0;
uint32_t serviceLastActivityMs = 0;

static gpio_num_t droneButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);
#else
    return GPIO_NUM_NC;
#endif
}

static void bluetoothOn()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    config.bluetooth.enabled = true;
    if (!nimbleBluetooth || !nimbleBluetooth->isActive())
        setBluetoothEnable(true);
#endif
}

static void bluetoothOff()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isActive())
        nimbleBluetooth->deinit();
    config.bluetooth.enabled = false;
#endif
}

static void startService()
{
    const uint32_t now = millis();
    serviceActive = true;
    serviceStartedMs = now;
    serviceLastActivityMs = now;
    bluetoothOn();
    LOG_INFO("Drone repeater: GPIO0 service opened; BLE idle=%us hard-cap=%us",
             (unsigned)(DRONE_BT_IDLE_MS / 1000UL), (unsigned)(DRONE_BT_HARD_CAP_MS / 1000UL));
}

static void stopService()
{
    if (!serviceActive)
        return;
    bluetoothOff();
    serviceActive = false;
    LOG_INFO("Drone repeater: BLE service closed after inactivity");
}

class DroneRepeaterServiceThread : public concurrency::OSThread
{
  public:
    DroneRepeaterServiceThread() : concurrency::OSThread("DroneRepeaterSvc") {}

  protected:
    int32_t runOnce() override
    {
        const uint32_t now = millis();
        const gpio_num_t button = droneButtonPin();
        const bool pressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;

        if (pressed && !buttonWasPressed) {
            buttonWasPressed = true;
            if (!serviceActive)
                startService();
            else
                serviceLastActivityMs = now;
        } else if (!pressed) {
            buttonWasPressed = false;
        }

        const uint32_t bleActivity = pendingBleActivityMs;
        if (serviceActive && bleActivity != 0) {
            serviceLastActivityMs = bleActivity;
            pendingBleActivityMs = 0;
        }

        if (serviceActive) {
            const bool idleExpired = (uint32_t)(now - serviceLastActivityMs) >= DRONE_BT_IDLE_MS;
            const bool hardCapExpired = (uint32_t)(now - serviceStartedMs) >= DRONE_BT_HARD_CAP_MS;
            if (idleExpired || hardCapExpired)
                stopService();
        }

        return 10;
    }
};

DroneRepeaterServiceThread *serviceThread = nullptr;
} // namespace

void droneRepeaterBleActivity()
{
    pendingBleActivityMs = millis() ? millis() : 1;
}

void setupHeltecTrackerV11DroneRepeaterPolicy()
{
    // A few old Tracker test builds persisted GPIO7 as the user button. Repair
    // that once so the stock Meshtastic button/display handler and our BLE
    // service both use the physical USER button on GPIO0.
    if (config.device.button_gpio != 0) {
        const uint8_t oldPin = config.device.button_gpio;
        config.device.button_gpio = 0;
        if (nodeDB)
            nodeDB->saveToDisk(SEGMENT_CONFIG);
        LOG_WARN("Drone repeater: repaired persisted button_gpio=%u -> GPIO0; rebooting once", (unsigned)oldPin);
        rebootAtMsec = millis() + 1500UL;
        return;
    }

    // Dedicated airborne profile: always act as a late repeater while continuing
    // to originate this node's own GNSS position packets.
    config.device.role = meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
    config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL;
    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;

    // Reliability first while airborne: no light/deep sleep and no Wi-Fi.
    config.power.is_power_saving = false;
    config.network.wifi_enabled = false;

    // Bluetooth is intentionally off until GPIO0 is pressed. The stock
    // Meshtastic display/button UI remains in control; no custom overlay is used.
    config.bluetooth.enabled = false;
    config.display.screen_on_secs = 20;

#if !MESHTASTIC_EXCLUDE_GPS
    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    // <=10 s keeps the GNSS receiver in the always-on path. At 1 s the local
    // position follows the aircraft closely, while LoRa TX remains throttled by
    // the separate 25 m / 10 s smart-position rules below.
    config.position.gps_update_interval = DRONE_GPS_UPDATE_SECS;
    config.position.position_broadcast_smart_enabled = true;
    config.position.broadcast_smart_minimum_distance = DRONE_SMART_DISTANCE_M;
    config.position.broadcast_smart_minimum_interval_secs = DRONE_SMART_INTERVAL_SECS;
    config.position.position_broadcast_secs = DRONE_GROUND_HEARTBEAT_SECS;

    // lateInitVariant runs after the GPS/Position objects may already have seen
    // the previously persisted role/settings. Force both subsystems active now
    // so switching from TAK_TRACKER or a GPS-disabled config cannot leave the
    // airborne profile dormant until another reboot/config change.
    if (gps)
        gps->enable();
    if (positionModule) {
        positionModule->refreshSmartPositionMinimumInterval();
        positionModule->setIntervalFromNow(0);
    }
#endif

    bluetoothOff();

    if (!serviceThread)
        serviceThread = new DroneRepeaterServiceThread();

    LOG_INFO("Drone repeater profile active: ROUTER_LATE, GPS=%us smart=%um/%us, broadcast=%us, no sleep, BLE on GPIO0",
             (unsigned)DRONE_GPS_UPDATE_SECS, (unsigned)DRONE_SMART_DISTANCE_M, (unsigned)DRONE_SMART_INTERVAL_SECS,
             (unsigned)DRONE_GROUND_HEARTBEAT_SECS);
}

#endif // HELTEC_TRACKER_V1_1 && JARNSEN_DRONE_REPEATER_BUILD
