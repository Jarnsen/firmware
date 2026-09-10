#include "jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h"

#include "configuration.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V4)

#include "NodeDB.h"
#include "PowerStatus.h"
#include "airtime.h"
#include "concurrency/OSThread.h"
#include "graphics/Screen.h"
#include "main.h"
#include "modules/PositionModule.h"

#if !MESHTASTIC_EXCLUDE_GPS
#include "GPS.h"
#endif

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#include <Arduino.h>
#include <math.h>

#ifdef ARCH_ESP32
#include <esp_system.h>
#endif

#endif

namespace jarnsen
{

bool droneRepeaterRoleActive()
{
    return activeDeviceRoleIs(DeviceRole::DRONE_REPEATER);
}

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V4)
namespace
{

constexpr uint32_t DRONE_SMART_DISTANCE_M = 25U;
constexpr uint32_t DRONE_SMART_INTERVAL_SECS = 10U;
constexpr uint32_t DRONE_GPS_UPDATE_SECS = 1U;
constexpr uint32_t DRONE_GROUND_HEARTBEAT_SECS = 30U;
constexpr uint32_t DRONE_BT_IDLE_MS = 120UL * 1000UL;
constexpr uint32_t DRONE_BT_HARD_CAP_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t DRONE_DYNAMIC_CHECK_MS = 500UL;
constexpr uint32_t DRONE_AIRUTIL_RETRY_MS = 5000UL;
constexpr uint32_t DRONE_HEALTH_LOG_MS = 60UL * 1000UL;
constexpr uint32_t DRONE_USB_DISPLAY_SECS = 20U;
constexpr uint32_t DRONE_BATTERY_DISPLAY_SECS = 10U;

bool runtimeInitialized = false;
bool serviceActive = false;
bool buttonWasPressed = false;
uint32_t serviceStartedMs = 0;
uint32_t serviceLastActivityMs = 0;
uint32_t observedBleTraffic = 0;

uint32_t lastDynamicCheckMs = 0;
uint32_t lastAirUtilCheckMs = 0;
uint32_t currentDynamicIntervalSecs = 0;
bool previousGpsFix = false;
bool everHadGpsFix = false;
bool immediateFixSendPending = false;

bool previousUsbKnown = false;
bool previousUsb = false;
bool previousGnssConnected = false;
uint32_t lastAccountingMs = 0;
uint32_t lastHealthLogMs = 0;
uint64_t gpsMs = 0;
uint64_t bleMs = 0;
uint64_t displayMs = 0;
uint32_t positionTxCount = 0;
uint32_t gpsRecoveryCount = 0;
uint32_t usbDropCount = 0;
uint32_t usbRestoreCount = 0;
uint32_t minFreeHeap = 0;

int droneButtonPin()
{
#ifdef BUTTON_PIN
    return config.device.button_gpio ? (int)config.device.button_gpio : (int)BUTTON_PIN;
#else
    return -1;
#endif
}

bool usbPowered()
{
    return powerStatus && powerStatus->getHasUSB();
}

void applyDisplayPowerPriority(bool usb)
{
    config.display.screen_on_secs = usb ? DRONE_USB_DISPLAY_SECS : DRONE_BATTERY_DISPLAY_SECS;
}

void bluetoothOn()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    config.bluetooth.enabled = true;
    if (nimbleBluetooth && nimbleBluetooth->isActive())
        nimbleBluetooth->resume();
    else
        setBluetoothEnable(true);
#endif
}

void bluetoothOff()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isActive())
        nimbleBluetooth->suspend();
    config.bluetooth.enabled = false;
#endif
}

void startService()
{
    const uint32_t now = millis();
    serviceActive = true;
    serviceStartedMs = now;
    serviceLastActivityMs = now;
    bluetoothOn();
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    observedBleTraffic = nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;
#endif
    diagnosticLog("DRONE_SERVICE", "OPEN ble_idle=%us hard_cap=%us usb=%u",
                  (unsigned)(DRONE_BT_IDLE_MS / 1000UL), (unsigned)(DRONE_BT_HARD_CAP_MS / 1000UL),
                  usbPowered() ? 1U : 0U);

#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT
    if (Serial)
        diagnosticLogRequestUsbExport(Serial);
#endif
}

void stopService(const char *reason)
{
    if (!serviceActive)
        return;
    bluetoothOff();
    serviceActive = false;
    diagnosticLog("DRONE_SERVICE", "CLOSED reason=%s", reason ? reason : "idle");
}

uint32_t speedTargetIntervalSecs(float speedKmh)
{
    if (speedKmh < 2.0f)
        return 30U;
    if (speedKmh < 15.0f)
        return 10U;
    if (speedKmh < 40.0f)
        return 7U;
    return 5U;
}

uint32_t applyChannelUtilizationBrake(uint32_t intervalSecs, float channelUtilization)
{
    uint32_t minimumSecs = 0;
    if (channelUtilization >= 25.0f)
        minimumSecs = 30U;
    else if (channelUtilization >= 20.0f)
        minimumSecs = 15U;
    else if (channelUtilization >= 15.0f)
        minimumSecs = 10U;
    return intervalSecs < minimumSecs ? minimumSecs : intervalSecs;
}

float distanceMeters(int32_t lat1E7, int32_t lon1E7, int32_t lat2E7, int32_t lon2E7)
{
    constexpr double DEG_TO_RAD_LOCAL = 0.017453292519943295769;
    constexpr double EARTH_RADIUS_M = 6371000.0;
    const double lat1 = (double)lat1E7 * 1.0e-7 * DEG_TO_RAD_LOCAL;
    const double lat2 = (double)lat2E7 * 1.0e-7 * DEG_TO_RAD_LOCAL;
    const double dLat = lat2 - lat1;
    const double dLon = ((double)lon2E7 - (double)lon1E7) * 1.0e-7 * DEG_TO_RAD_LOCAL;
    const double sinLat = sin(dLat * 0.5);
    const double sinLon = sin(dLon * 0.5);
    double a = sinLat * sinLat + cos(lat1) * cos(lat2) * sinLon * sinLon;
    if (a < 0.0)
        a = 0.0;
    else if (a > 1.0)
        a = 1.0;
    return (float)(2.0 * EARTH_RADIUS_M * atan2(sqrt(a), sqrt(1.0 - a)));
}

bool positionTxAllowed(uint32_t now, float channelUtilization)
{
    if (!airTime)
        return true;
    if (channelUtilization >= 25.0f)
        return false;
    if (lastAirUtilCheckMs != 0 && (uint32_t)(now - lastAirUtilCheckMs) < DRONE_AIRUTIL_RETRY_MS)
        return false;
    lastAirUtilCheckMs = now ? now : 1U;
    return airTime->isTxAllowedAirUtil();
}

void sendDronePosition(uint32_t now, const char *reason, float speedKmh, float channelUtilization)
{
#if !MESHTASTIC_EXCLUDE_GPS
    if (!positionModule || !gps)
        return;
    const int32_t lat = gps->p.latitude_i;
    const int32_t lon = gps->p.longitude_i;
    if (lat == 0 && lon == 0)
        return;

    positionModule->sendOurPosition();
    positionModule->noteExternalPositionSend(now ? now : 1U, lat, lon);
    positionTxCount++;
    diagnosticLog("DRONE_POSITION_TX", "%s speed=%.1fkm/h cu=%.1f%% interval=%us lat=%d lon=%d",
                  reason ? reason : "policy", (double)speedKmh, (double)channelUtilization,
                  (unsigned)currentDynamicIntervalSecs, lat, lon);
#else
    (void)now;
    (void)reason;
    (void)speedKmh;
    (void)channelUtilization;
#endif
}

void updateDynamicPositionPolicy(uint32_t now)
{
#if !MESHTASTIC_EXCLUDE_GPS
    if ((uint32_t)(now - lastDynamicCheckMs) < DRONE_DYNAMIC_CHECK_MS)
        return;
    lastDynamicCheckMs = now;

    if (!gps || !positionModule)
        return;

    const bool hasFix = gps->hasLock() && nodeDB && nodeDB->hasLocalPositionSinceBoot() &&
                        (gps->p.latitude_i != 0 || gps->p.longitude_i != 0);

    if (hasFix && !previousGpsFix) {
        immediateFixSendPending = true;
        if (everHadGpsFix) {
            gpsRecoveryCount++;
            diagnosticLog("DRONE_GPS", "FIX_RESTORED sats=%u recoveries=%u", (unsigned)gps->p.sats_in_view,
                          (unsigned)gpsRecoveryCount);
        } else {
            diagnosticLog("DRONE_GPS", "FIX_ACQUIRED sats=%u", (unsigned)gps->p.sats_in_view);
        }
        everHadGpsFix = true;
    } else if (!hasFix && previousGpsFix) {
        diagnosticLog("DRONE_GPS", "FIX_LOST holding_last_mesh_position=1");
    }
    previousGpsFix = hasFix;

    if (!hasFix)
        return;

    const float speedKmh = (float)gps->p.ground_speed;
    const float channelUtilization = airTime ? airTime->channelUtilizationPercent() : 0.0f;
    const uint32_t speedInterval = speedTargetIntervalSecs(speedKmh);
    const uint32_t targetInterval = applyChannelUtilizationBrake(speedInterval, channelUtilization);

    if (targetInterval != currentDynamicIntervalSecs) {
        currentDynamicIntervalSecs = targetInterval;
        config.position.broadcast_smart_minimum_interval_secs = targetInterval;
        positionModule->refreshSmartPositionMinimumInterval();
        diagnosticLog("DRONE_POSITION_POLICY", "speed=%.1fkm/h cu=%.1f%% interval=%us distance=%um",
                      (double)speedKmh, (double)channelUtilization, (unsigned)targetInterval,
                      (unsigned)DRONE_SMART_DISTANCE_M);
    }

    if (immediateFixSendPending) {
        if (positionTxAllowed(now, channelUtilization)) {
            sendDronePosition(now, "fresh-fix", speedKmh, channelUtilization);
            immediateFixSendPending = false;
        }
        return;
    }

    const uint32_t lastTxMs = positionModule->lastPositionSendMs();
    if (lastTxMs != 0 && (uint32_t)(now - lastTxMs) < targetInterval * 1000UL)
        return;

    const char *reason = nullptr;
    if (speedKmh < 2.0f) {
        reason = "ground-heartbeat";
    } else {
        const int32_t lastLat = positionModule->lastPositionLatitudeE7();
        const int32_t lastLon = positionModule->lastPositionLongitudeE7();
        if (lastLat == 0 && lastLon == 0) {
            reason = "no-previous-tx";
        } else if (distanceMeters(lastLat, lastLon, gps->p.latitude_i, gps->p.longitude_i) >=
                   (float)DRONE_SMART_DISTANCE_M) {
            reason = "distance";
        }
    }

    if (reason && positionTxAllowed(now, channelUtilization))
        sendDronePosition(now, reason, speedKmh, channelUtilization);
#else
    (void)now;
#endif
}

void updatePowerAndHealth(uint32_t now)
{
    const uint32_t delta = lastAccountingMs == 0 ? 0U : now - lastAccountingMs;
    lastAccountingMs = now;
    if (delta <= 10UL * 60UL * 1000UL) {
#if !MESHTASTIC_EXCLUDE_GPS
        if (gps && gps->isEnabled())
            gpsMs += delta;
#endif
        if (serviceActive)
            bleMs += delta;
        if (screen && screen->isScreenOn())
            displayMs += delta;
    }

    const bool usb = usbPowered();
    if (!previousUsbKnown) {
        previousUsbKnown = true;
        previousUsb = usb;
        applyDisplayPowerPriority(usb);
    } else if (usb != previousUsb) {
        if (usb)
            usbRestoreCount++;
        else
            usbDropCount++;
        previousUsb = usb;
        applyDisplayPowerPriority(usb);
        diagnosticLog("DRONE_POWER_SOURCE", "%s drops=%u restores=%u battery=%u%%",
                      usb ? "USB_RESTORED" : "USB_LOST_BATTERY", (unsigned)usbDropCount,
                      (unsigned)usbRestoreCount,
                      powerStatus && powerStatus->getHasBattery() ? (unsigned)powerStatus->getBatteryChargePercent() : 0U);
    }

#if !MESHTASTIC_EXCLUDE_GPS
    const bool gnssConnected = gps && gps->isConnected();
#else
    const bool gnssConnected = false;
#endif
    if (gnssConnected != previousGnssConnected) {
        previousGnssConnected = gnssConnected;
        const auto profile = currentHardwareRoleProfile();
        diagnosticLog("DRONE_GNSS", "connected=%u integrated=%u external_required=%u", gnssConnected ? 1U : 0U,
                      profile.hardware.capabilities.internalGps ? 1U : 0U,
                      (!profile.hardware.capabilities.internalGps && profile.hardware.capabilities.supportsExternalGps) ? 1U : 0U);
    }

#ifdef ARCH_ESP32
    const uint32_t freeHeap = ESP.getFreeHeap();
    if (minFreeHeap == 0 || freeHeap < minFreeHeap)
        minFreeHeap = freeHeap;
#endif

    if (lastHealthLogMs == 0 || (uint32_t)(now - lastHealthLogMs) >= DRONE_HEALTH_LOG_MS) {
        lastHealthLogMs = now ? now : 1U;
        const float cu = airTime ? airTime->channelUtilizationPercent() : 0.0f;
        diagnosticLog("DRONE_HEALTH",
                      "usb=%u gps_s=%lu ble_s=%lu display_s=%lu pos_tx=%u gps_recovery=%u cu=%.1f%% min_heap=%u",
                      usb ? 1U : 0U, (unsigned long)(gpsMs / 1000ULL), (unsigned long)(bleMs / 1000ULL),
                      (unsigned long)(displayMs / 1000ULL), (unsigned)positionTxCount, (unsigned)gpsRecoveryCount,
                      (double)cu, (unsigned)minFreeHeap);
    }
}

class DroneRepeaterRuntimeThread final : public concurrency::OSThread
{
  public:
    DroneRepeaterRuntimeThread() : concurrency::OSThread("JarnsenDrone") {}

  protected:
    int32_t runOnce() override
    {
        if (!droneRepeaterRoleActive()) {
            stopService("role-changed");
            return 1000;
        }

        const uint32_t now = millis();
        updateDynamicPositionPolicy(now);
        updatePowerAndHealth(now);

        const int pin = droneButtonPin();
        const bool pressed = pin >= 0 && digitalRead((uint8_t)pin) == LOW;
        if (pressed && !buttonWasPressed) {
            buttonWasPressed = true;
            if (!serviceActive)
                startService();
            else
                serviceLastActivityMs = now;
        } else if (!pressed) {
            buttonWasPressed = false;
        }

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
        if (serviceActive && nimbleBluetooth) {
            const uint32_t traffic = nimbleBluetooth->getMeaningfulTrafficCount();
            if (traffic != observedBleTraffic) {
                observedBleTraffic = traffic;
                serviceLastActivityMs = now;
                diagnosticLog("DRONE_BT_ACTIVITY", "meaningful traffic; idle timer reset");
            }
        }
#endif

        if (serviceActive) {
            const bool idle = (uint32_t)(now - serviceLastActivityMs) >= DRONE_BT_IDLE_MS;
            const bool hardCap = (uint32_t)(now - serviceStartedMs) >= DRONE_BT_HARD_CAP_MS;
            if (hardCap)
                stopService("hard-cap");
            else if (idle)
                stopService("idle");
        }

        return 10;
    }
};

DroneRepeaterRuntimeThread *runtimeThread = nullptr;

} // namespace

bool droneRepeaterApplyBaseConfig(bool persist)
{
    bool changed = false;

#define SET_IF_CHANGED(field, value)                                                                                             \
    do {                                                                                                                         \
        const auto desiredValue = (value);                                                                                       \
        if ((field) != desiredValue) {                                                                                           \
            (field) = desiredValue;                                                                                              \
            changed = true;                                                                                                      \
        }                                                                                                                        \
    } while (0)

    SET_IF_CHANGED(config.device.role, meshtastic_Config_DeviceConfig_Role_ROUTER_LATE);
    SET_IF_CHANGED(config.device.rebroadcast_mode, meshtastic_Config_DeviceConfig_RebroadcastMode_ALL);
#ifdef BUTTON_PIN
    SET_IF_CHANGED(config.device.button_gpio, (uint8_t)BUTTON_PIN);
#endif
    SET_IF_CHANGED(config.device.disable_triple_click, true);
    SET_IF_CHANGED(config.device.led_heartbeat_disabled, true);
    SET_IF_CHANGED(config.power.is_power_saving, false);
    SET_IF_CHANGED(config.network.wifi_enabled, false);
    SET_IF_CHANGED(config.bluetooth.enabled, false);

    const uint32_t displaySecs = usbPowered() ? DRONE_USB_DISPLAY_SECS : DRONE_BATTERY_DISPLAY_SECS;
    SET_IF_CHANGED(config.display.screen_on_secs, displaySecs);

#if !MESHTASTIC_EXCLUDE_GPS
    SET_IF_CHANGED(config.position.gps_mode, meshtastic_Config_PositionConfig_GpsMode_ENABLED);
    SET_IF_CHANGED(config.position.fixed_position, false);
    SET_IF_CHANGED(config.position.gps_update_interval, DRONE_GPS_UPDATE_SECS);
    SET_IF_CHANGED(config.position.position_broadcast_smart_enabled, true);
    SET_IF_CHANGED(config.position.broadcast_smart_minimum_distance, DRONE_SMART_DISTANCE_M);
    SET_IF_CHANGED(config.position.broadcast_smart_minimum_interval_secs, DRONE_SMART_INTERVAL_SECS);
    SET_IF_CHANGED(config.position.position_broadcast_secs, DRONE_GROUND_HEARTBEAT_SECS);
#endif

#undef SET_IF_CHANGED

    if (persist && changed) {
        if (!nodeDB || !nodeDB->saveToDisk(SEGMENT_CONFIG)) {
            diagnosticLog("DRONE_PROFILE", "persist=ERROR");
            return false;
        }
    }

    if (changed)
        diagnosticLog("DRONE_PROFILE", "base_config=applied persist=%u", persist ? 1U : 0U);
    return true;
}

void droneRepeaterRuntimeInit()
{
    if (runtimeInitialized || !droneRepeaterRoleActive())
        return;

    if (!droneRepeaterApplyBaseConfig(true)) {
        diagnosticLog("DRONE_PROFILE", "runtime_init=blocked reason=config_persist_failed");
        return;
    }

    const int pin = droneButtonPin();
    if (pin >= 0)
        pinMode((uint8_t)pin, INPUT_PULLUP);

#if !MESHTASTIC_EXCLUDE_GPS
    if (gps)
        gps->enable();
#endif

    bluetoothOff();

    previousUsbKnown = false;
    previousGpsFix = false;
    everHadGpsFix = false;
    immediateFixSendPending = false;
    currentDynamicIntervalSecs = 0;
    lastDynamicCheckMs = 0;
    lastAirUtilCheckMs = 0;
    lastAccountingMs = millis();
    minFreeHeap = 0;

    const auto profile = currentHardwareRoleProfile();
#ifdef ARCH_ESP32
    diagnosticLog("DRONE_BOOT", "board=%s reset_reason=%d external_gnss_required=%u no_sleep=1",
                  profile.hardware.displayName, (int)esp_reset_reason(),
                  (!profile.hardware.capabilities.internalGps && profile.hardware.capabilities.supportsExternalGps) ? 1U : 0U);
#else
    diagnosticLog("DRONE_BOOT", "board=%s external_gnss_required=%u no_sleep=1",
                  profile.hardware.displayName,
                  (!profile.hardware.capabilities.internalGps && profile.hardware.capabilities.supportsExternalGps) ? 1U : 0U);
#endif

    if (!runtimeThread)
        runtimeThread = new DroneRepeaterRuntimeThread();
    runtimeInitialized = true;
}

#else

bool droneRepeaterApplyBaseConfig(bool persist)
{
    (void)persist;
    return false;
}

void droneRepeaterRuntimeInit() {}

#endif

} // namespace jarnsen
