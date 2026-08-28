#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)

#include "GPS.h"
#include "NodeDB.h"
#include "airtime.h"
#include "concurrency/OSThread.h"
#include "drone/DroneDiagnosticLog.h"
#include "drone/DronePowerMonitor.h"
#include "drone/DroneStatusPages.h"
#include "drone/DroneSystemHealth.h"
#include "graphics/Screen.h"
#include "main.h"
#include "modules/PositionModule.h"

#include <driver/gpio.h>
#include <math.h>

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
#ifndef DRONE_DYNAMIC_CHECK_MS
#define DRONE_DYNAMIC_CHECK_MS 500UL
#endif
#ifndef DRONE_AIRUTIL_RETRY_MS
#define DRONE_AIRUTIL_RETRY_MS 5000UL
#endif

namespace {
volatile uint32_t pendingBleActivityMs = 0;
bool serviceActive = false;
bool buttonWasPressed = false;
uint32_t serviceStartedMs = 0;
uint32_t serviceLastActivityMs = 0;

uint32_t lastDynamicCheckMs = 0;
uint32_t lastAirUtilCheckMs = 0;
uint32_t currentDynamicIntervalSecs = 0;
bool previousGpsFix = false;
bool everHadGpsFix = false;
bool immediateFixSendPending = false;
uint32_t lastStatusRefreshMs = 0;

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
    droneDiagLog("SERVICE", "OPEN ble_idle=%us hard_cap=%us usb=%u", (unsigned)(DRONE_BT_IDLE_MS / 1000UL),
                 (unsigned)(DRONE_BT_HARD_CAP_MS / 1000UL), Serial ? 1U : 0U);
    // With a PC/service tool attached, one GPIO0 press both opens BLE service
    // and starts the shared USB log snapshot. A power-only USB source has no
    // CDC connection, so it never triggers an export.
    if (Serial)
        droneDiagRequestUsbExport();
}

static void stopService()
{
    if (!serviceActive)
        return;
    bluetoothOff();
    serviceActive = false;
    droneDiagLog("SERVICE", "CLOSED inactivity");
    LOG_INFO("Drone repeater: BLE service closed after inactivity");
}

static uint32_t speedTargetIntervalSecs(float speedKmh)
{
    if (speedKmh < 2.0f)
        return 30U;
    if (speedKmh < 15.0f)
        return 10U;
    if (speedKmh < 40.0f)
        return 7U;
    return 5U;
}

static uint32_t applyChannelUtilizationBrake(uint32_t intervalSecs, float channelUtilization)
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

static float distanceMeters(int32_t lat1E7, int32_t lon1E7, int32_t lat2E7, int32_t lon2E7)
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

static bool positionTxAllowed(uint32_t now, float channelUtilization)
{
    if (!airTime)
        return true;

    if (channelUtilization >= 25.0f)
        return false;

    if (lastAirUtilCheckMs != 0 && (uint32_t)(now - lastAirUtilCheckMs) < DRONE_AIRUTIL_RETRY_MS)
        return false;
    lastAirUtilCheckMs = now ? now : 1;
    return airTime->isTxAllowedAirUtil();
}

static void sendDronePosition(uint32_t now, const char *reason, float speedKmh, float channelUtilization)
{
    if (!positionModule || !gps)
        return;

    const int32_t lat = gps->p.latitude_i;
    const int32_t lon = gps->p.longitude_i;
    if (lat == 0 && lon == 0)
        return;

    positionModule->sendOurPosition();
    positionModule->noteExternalPositionSend(now ? now : 1, lat, lon);
    dronePowerMonitorNotePositionTx();
    droneDiagLog("POSITION_TX", "%s speed=%.1fkm/h cu=%.1f%% interval=%us lat=%d lon=%d", reason, speedKmh,
                 channelUtilization, (unsigned)currentDynamicIntervalSecs, lat, lon);
    LOG_INFO("Drone position TX: %s speed=%.1fkm/h cu=%.1f%% interval=%us lat=%d lon=%d", reason, speedKmh,
             channelUtilization, (unsigned)currentDynamicIntervalSecs, lat, lon);
}

static void updateDynamicPositionPolicy(uint32_t now)
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
            droneSystemHealthNoteGpsRecovery();
            droneDiagLog("GPS", "FIX_RESTORED sats=%u", (unsigned)gps->p.sats_in_view);
        } else {
            droneDiagLog("GPS", "FIX_ACQUIRED sats=%u", (unsigned)gps->p.sats_in_view);
        }
        everHadGpsFix = true;
        LOG_INFO("Drone repeater: GNSS fix acquired/restored; immediate position queued");
    } else if (!hasFix && previousGpsFix) {
        droneDiagLog("GPS", "FIX_LOST");
        LOG_WARN("Drone repeater: GNSS fix lost; holding last mesh position until a fresh fix returns");
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
        droneDiagLog("POSITION_POLICY", "speed=%.1fkm/h cu=%.1f%% interval=%us distance=%um", speedKmh,
                     channelUtilization, (unsigned)targetInterval, (unsigned)DRONE_SMART_DISTANCE_M);
        LOG_INFO("Drone dynamic profile: speed=%.1fkm/h cu=%.1f%% -> min interval=%us, distance=%um", speedKmh,
                 channelUtilization, (unsigned)targetInterval, (unsigned)DRONE_SMART_DISTANCE_M);
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
        } else {
            const float movedM = distanceMeters(lastLat, lastLon, gps->p.latitude_i, gps->p.longitude_i);
            if (movedM >= (float)DRONE_SMART_DISTANCE_M)
                reason = "distance";
        }
    }

    if (reason && positionTxAllowed(now, channelUtilization))
        sendDronePosition(now, reason, speedKmh, channelUtilization);
#endif
}

class DroneRepeaterServiceThread : public concurrency::OSThread
{
  public:
    DroneRepeaterServiceThread() : concurrency::OSThread("DroneRepeaterSvc") {}

  protected:
    int32_t runOnce() override
    {
        const uint32_t now = millis();
        updateDynamicPositionPolicy(now);

        const bool gpsActive = gps != nullptr;
        const bool displayActive = screen && screen->isScreenOn();
        dronePowerMonitorTick(gpsActive, serviceActive, displayActive);
        droneSystemHealthTick();
        droneDiagTick();

        if (lastStatusRefreshMs == 0 || (uint32_t)(now - lastStatusRefreshMs) >= 1000UL) {
            lastStatusRefreshMs = now ? now : 1;
            droneStatusPagesRefresh();
        }

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
    if (config.device.button_gpio != 0) {
        const uint8_t oldPin = config.device.button_gpio;
        config.device.button_gpio = 0;
        if (nodeDB)
            nodeDB->saveToDisk(SEGMENT_CONFIG);
        LOG_WARN("Drone repeater: repaired persisted button_gpio=%u -> GPIO0; rebooting once", (unsigned)oldPin);
        rebootAtMsec = millis() + 1500UL;
        return;
    }

    config.device.role = meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
    config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL;
    config.device.button_gpio = 0;
    config.device.disable_triple_click = true;
    config.device.led_heartbeat_disabled = true;

    // Drone priority: radio + GNSS remain fully awake on both USB and battery.
    // The PowerFSM build hook treats this dedicated profile as continuously
    // powered; this runtime monitor independently records the real source.
    config.power.is_power_saving = false;
    config.network.wifi_enabled = false;

    config.bluetooth.enabled = false;
    config.display.screen_on_secs = 20;

#if !MESHTASTIC_EXCLUDE_GPS
    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;
    config.position.fixed_position = false;
    config.position.gps_update_interval = DRONE_GPS_UPDATE_SECS;
    config.position.position_broadcast_smart_enabled = true;
    config.position.broadcast_smart_minimum_distance = DRONE_SMART_DISTANCE_M;
    config.position.broadcast_smart_minimum_interval_secs = DRONE_SMART_INTERVAL_SECS;
    config.position.position_broadcast_secs = DRONE_GROUND_HEARTBEAT_SECS;

    if (gps)
        gps->enable();
    if (positionModule)
        positionModule->refreshSmartPositionMinimumInterval();
#endif

    lastDynamicCheckMs = 0;
    lastAirUtilCheckMs = 0;
    currentDynamicIntervalSecs = 0;
    previousGpsFix = false;
    everHadGpsFix = false;
    immediateFixSendPending = false;
    lastStatusRefreshMs = 0;

    droneSystemHealthInit();
    dronePowerMonitorInit();
    droneDiagInit();
    setupDroneStatusPages();

    bluetoothOff();

    if (!serviceThread)
        serviceThread = new DroneRepeaterServiceThread();

    droneDiagLog("PROFILE", "ROUTER_LATE gps=%us distance=%um dynamic=30/10/7/5s cu_brake=15/20/25 no_sleep power=%s",
                 (unsigned)DRONE_GPS_UPDATE_SECS, (unsigned)DRONE_SMART_DISTANCE_M, dronePowerSourceText());
    LOG_INFO("Drone repeater profile active: ROUTER_LATE, GPS=%us, distance=%um, dynamic=30/10/7/5s, CU brake=15/20/25%%, no sleep, BLE on GPIO0",
             (unsigned)DRONE_GPS_UPDATE_SECS, (unsigned)DRONE_SMART_DISTANCE_M);
}

#endif // HELTEC_TRACKER_V1_1 && JARNSEN_DRONE_REPEATER_BUILD
