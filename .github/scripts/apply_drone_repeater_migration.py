from pathlib import Path

ROOT = Path('.')


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{path}: expected exactly one occurrence, got {count}: {old[:140]!r}')
    write(path, text.replace(old, new, 1))


def require(path: str, needle: str) -> None:
    if needle not in read(path):
        raise RuntimeError(f'{path}: required marker missing: {needle!r}')


# 1. Stable role key used by firmware and flasher.
replace_once(
    'src/jarnsen/core/roles/JarnsenDeviceRole.h',
    '''constexpr const char *roleName(DeviceRole role)
{
    switch (role) {
    case DeviceRole::TAK:
        return "TAK";
    case DeviceRole::TAK_TRACKER:
        return "TAK Tracker";
    case DeviceRole::TAK_REPEATER:
        return "TAK Repeater";
    case DeviceRole::DRONE_REPEATER:
        return "Drone Repeater";
    case DeviceRole::UNCONFIGURED:
    default:
        return "Unconfigured";
    }
}
''',
    '''constexpr const char *roleName(DeviceRole role)
{
    switch (role) {
    case DeviceRole::TAK:
        return "TAK";
    case DeviceRole::TAK_TRACKER:
        return "TAK Tracker";
    case DeviceRole::TAK_REPEATER:
        return "TAK Repeater";
    case DeviceRole::DRONE_REPEATER:
        return "Drone Repeater";
    case DeviceRole::UNCONFIGURED:
    default:
        return "Unconfigured";
    }
}

constexpr const char *roleKey(DeviceRole role)
{
    switch (role) {
    case DeviceRole::TAK:
        return "tak";
    case DeviceRole::TAK_TRACKER:
        return "tak_tracker";
    case DeviceRole::TAK_REPEATER:
        return "tak_repeater";
    case DeviceRole::DRONE_REPEATER:
        return "drone_repeater";
    case DeviceRole::UNCONFIGURED:
    default:
        return "unconfigured";
    }
}
''')


# 2. Deliberate board role availability: Tracker V1.1 + Heltec V4 only.
hardware = read('src/jarnsen/hardware/JarnsenHardwareProfiles.h')
old_v4 = '''constexpr HardwareRoleProfile heltecV4Profile()
{
    return {
        {
            HardwareKind::BOARD_HELTEC_V4,
            "HELTEC_V4",
            "Heltec V4",
            {
                false,
                true,
                {true, 128, 64, false, false},
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                false,
                false,
            },
        },
        {true, true, true, false},
    };
}
'''
new_v4 = old_v4.replace('{true, true, true, false},', '{true, true, true, true},')
if hardware.count(old_v4) != 1:
    raise RuntimeError('JarnsenHardwareProfiles.h: Heltec V4 profile shape changed')
hardware = hardware.replace(old_v4, new_v4, 1)
current_helper = '''
constexpr HardwareRoleProfile currentHardwareRoleProfile()
{
#if defined(HELTEC_TRACKER_V1_1)
    return trackerV11Profile();
#elif defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
    return heltecV3Profile();
#elif defined(HELTEC_V4)
    return heltecV4Profile();
#elif defined(SEEED_WIO_TRACKER_L1)
    return seeedWioTrackerL1Profile();
#elif defined(TBEAM_V10)
    return lilygoTBeamProfile();
#elif defined(LILYGO_TBEAM_S3_CORE)
    return lilygoTBeamSupremeProfile();
#else
    return {};
#endif
}
'''
namespace_end = '\n} // namespace jarnsen\n'
if current_helper.strip() in hardware:
    raise RuntimeError('JarnsenHardwareProfiles.h: current hardware helper already exists')
if hardware.count(namespace_end) != 1:
    raise RuntimeError('JarnsenHardwareProfiles.h: namespace end marker changed')
hardware = hardware.replace(namespace_end, current_helper + namespace_end, 1)
write('src/jarnsen/hardware/JarnsenHardwareProfiles.h', hardware)


# 3. Persistent role API. The record is revalidated against the current board
# every time it is first loaded, so copying a filesystem between boards cannot
# unlock Drone Repeater on V3/Wio/T-Beam/T-Beam Supreme.
write('src/jarnsen/core/roles/JarnsenRolePersistence.h', '''#pragma once

#include "jarnsen/core/roles/JarnsenDeviceRole.h"

#include <stdint.h>

namespace jarnsen
{

constexpr uint8_t JARNSEN_ROLE_API_VERSION = 1U;

bool parseDeviceRoleKey(const char *text, DeviceRole &role);
bool deviceRoleAllowedOnCurrentHardware(DeviceRole role);
bool readPersistedDeviceRole(DeviceRole &role);
bool writePersistedDeviceRole(DeviceRole role);

} // namespace jarnsen
''')

write('src/jarnsen/core/roles/JarnsenRolePersistence.cpp', '''#include "jarnsen/core/roles/JarnsenRolePersistence.h"

#include "FSCommon.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

#include <ctype.h>

namespace jarnsen
{
namespace
{

constexpr const char *ROLE_PATH = "/prefs/jarnsen-role-v1";
constexpr uint8_t ROLE_MAGIC = 0xD7U;
constexpr uint8_t ROLE_RECORD_VERSION = 1U;

bool cacheLoaded = false;
bool cacheKnown = false;
DeviceRole cachedRole = DeviceRole::UNCONFIGURED;

bool equalIgnoreCase(const char *a, const char *b)
{
    if (!a || !b)
        return false;
    while (*a && *b) {
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return false;
        ++a;
        ++b;
    }
    return *a == '\\0' && *b == '\\0';
}

bool decodeRole(int raw, DeviceRole &role)
{
    if (raw < (int)DeviceRole::UNCONFIGURED || raw > (int)DeviceRole::DRONE_REPEATER)
        return false;
    role = static_cast<DeviceRole>((uint8_t)raw);
    return true;
}

uint8_t roleChecksum(uint8_t role)
{
    return (uint8_t)(ROLE_MAGIC ^ ROLE_RECORD_VERSION ^ role ^ 0x5AU);
}

} // namespace

bool parseDeviceRoleKey(const char *text, DeviceRole &role)
{
    if (equalIgnoreCase(text, "unconfigured")) {
        role = DeviceRole::UNCONFIGURED;
        return true;
    }
    if (equalIgnoreCase(text, "tak")) {
        role = DeviceRole::TAK;
        return true;
    }
    if (equalIgnoreCase(text, "tak_tracker")) {
        role = DeviceRole::TAK_TRACKER;
        return true;
    }
    if (equalIgnoreCase(text, "tak_repeater")) {
        role = DeviceRole::TAK_REPEATER;
        return true;
    }
    if (equalIgnoreCase(text, "drone_repeater")) {
        role = DeviceRole::DRONE_REPEATER;
        return true;
    }
    return false;
}

bool deviceRoleAllowedOnCurrentHardware(DeviceRole role)
{
    if (role == DeviceRole::UNCONFIGURED)
        return true;
    const auto profile = currentHardwareRoleProfile();
    return profile.hardware.kind != HardwareKind::UNKNOWN && roleAllowed(role, profile.roles);
}

bool readPersistedDeviceRole(DeviceRole &role)
{
    if (cacheLoaded) {
        role = cachedRole;
        return cacheKnown;
    }

    role = DeviceRole::UNCONFIGURED;
    cacheLoaded = true;
    cacheKnown = false;
    cachedRole = DeviceRole::UNCONFIGURED;

#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(ROLE_PATH, FILE_O_READ);
    if (!file)
        return false;

    const int magic = file.read();
    const int version = file.read();
    const int raw = file.read();
    const int checksum = file.read();
    file.close();

    DeviceRole decoded = DeviceRole::UNCONFIGURED;
    if (magic != ROLE_MAGIC || version != ROLE_RECORD_VERSION || checksum < 0 || !decodeRole(raw, decoded) ||
        checksum != roleChecksum((uint8_t)raw))
        return false;

    if (!deviceRoleAllowedOnCurrentHardware(decoded))
        return false;

    cachedRole = decoded;
    cacheKnown = true;
    role = decoded;
    return true;
#else
    return false;
#endif
}

bool writePersistedDeviceRole(DeviceRole role)
{
    if (!deviceRoleAllowedOnCurrentHardware(role))
        return false;

#ifdef FSCom
    const uint8_t raw = static_cast<uint8_t>(role);
    const uint8_t record[4] = {ROLE_MAGIC, ROLE_RECORD_VERSION, raw, roleChecksum(raw)};

    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(ROLE_PATH, FILE_O_WRITE);
    if (!file)
        return false;
    const bool ok = file.write(record, sizeof(record)) == sizeof(record);
    file.flush();
    file.close();
    if (ok) {
        cacheLoaded = true;
        cacheKnown = true;
        cachedRole = role;
    }
    return ok;
#else
    return false;
#endif
}

} // namespace jarnsen
''')


# 4. Status bridge: persistent role first, legacy role only as migration fallback;
# V3/V4 external GNSS is a runtime peripheral fact, not a role unlock.
replace_once(
    'src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp',
    '''#include "jarnsen/core/status/JarnsenStatusProvider.h"

#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerServiceSettings.h"
#endif
''',
    '''#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"

#if !MESHTASTIC_EXCLUDE_GPS
#include "GPS.h"
#endif

#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerServiceSettings.h"
#endif
''')

replace_once(
    'src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp',
    '''bool readLegacyRole(DeviceRole &role)
{
    // DRONE_REPEATER historically used its own JARNSEN build marker rather than
''',
    '''bool readLegacyRole(DeviceRole &role)
{
    // role_api=1 persistence is authoritative. Proven legacy mappings remain a
    // migration fallback only for nodes that have not been provisioned yet.
    if (readPersistedDeviceRole(role))
        return true;

    // DRONE_REPEATER historically used its own JARNSEN build marker rather than
''')

replace_once(
    'src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp',
    '''#if defined(HELTEC_TRACKER_V1_1)
PeripheralCapabilities readTrackerPeripherals()
{
    PeripheralCapabilities peripherals{};
#ifdef VEHICLE_MOTION_WAKE_PIN
    peripherals.motion = true;
#endif
    peripherals.ina226 = trackerIna226Enabled();
    return peripherals;
}
#endif
''',
    '''#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4)
PeripheralCapabilities readRuntimePeripherals()
{
    PeripheralCapabilities peripherals{};
#if defined(HELTEC_TRACKER_V1_1)
#ifdef VEHICLE_MOTION_WAKE_PIN
    peripherals.motion = true;
#endif
    peripherals.ina226 = trackerIna226Enabled();
#endif

#if !MESHTASTIC_EXCLUDE_GPS && (defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4))
    peripherals.externalGps = gps && gps->isConnected();
#endif
    return peripherals;
}
#endif
''')

replace_once(
    'src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp',
    '''#if defined(HELTEC_TRACKER_V1_1)
    setPeripheralCapabilitiesProvider(readTrackerPeripherals);
#endif
''',
    '''#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4)
    setPeripheralCapabilitiesProvider(readRuntimePeripherals);
#endif
''')


# 5. Hardware-neutral Drone Repeater runtime, compiled only for the two allowed
# hardware families. Shared diagnostics replace the old duplicate Drone logger;
# the Unified five-page display replaces board-specific Drone status pages.
write('src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h', '''#pragma once

namespace jarnsen
{

bool droneRepeaterRoleActive();
bool droneRepeaterApplyBaseConfig(bool persist);
void droneRepeaterRuntimeInit();

} // namespace jarnsen
''')

write('src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp', r'''#include "jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h"

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
''')


# 6. Core runtime initializes normalized role and Drone policy before PowerFSM.
replace_once(
    'src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp',
    '''#include "jarnsen/core/runtime/JarnsenRuntimePolicy.h"

#include "FSCommon.h"
''',
    '''#include "jarnsen/core/runtime/JarnsenRuntimePolicy.h"

#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "FSCommon.h"
''')

replace_once(
    'src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp',
    '''    diagnosticLogInit();

    // JARNSEN operator UI rule: the display remains on for exactly 20 seconds
''',
    '''    diagnosticLogInit();
    ensureLegacyStatusBridge();

    // JARNSEN operator UI rule: the display remains on for exactly 20 seconds
''')

replace_once(
    'src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp',
    '''    config.display.screen_on_secs = JARNSEN_DISPLAY_ON_MS / 1000U;

    diagnosticLog("BOOT_RUNTIME", "board=%s platform=%s wake=%s button_pin=%d display_on_ms=%u", build::hardwareName,
''',
    '''    config.display.screen_on_secs = JARNSEN_DISPLAY_ON_MS / 1000U;

    if (activeDeviceRoleIs(DeviceRole::DRONE_REPEATER) && !droneRepeaterApplyBaseConfig(true))
        LOG_ERROR("JARNSEN: Drone Repeater base configuration could not be persisted");

    diagnosticLog("BOOT_RUNTIME", "board=%s platform=%s wake=%s button_pin=%d display_on_ms=%u", build::hardwareName,
''')

replace_once(
    'src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp',
    '''#else
    diagnosticLog("WAKE", "deep_capability=platform_specific button_pin=%d", configuredUserButtonPin());
#endif
#endif
}
''',
    '''#else
    diagnosticLog("WAKE", "deep_capability=platform_specific button_pin=%d", configuredUserButtonPin());
#endif

    droneRepeaterRuntimeInit();
#endif
}
''')


# 7. Share the PositionModule send clock with the Drone policy to avoid duplicate
# normal/smart/external transmissions.
replace_once(
    'src/modules/PositionModule.h',
    '''    }

    // Pure broadcast-policy helpers, split out so they're unit-testable without
''',
    '''    }

    void noteExternalPositionSend(uint32_t whenMs, int32_t latitudeE7, int32_t longitudeE7);
    uint32_t lastPositionSendMs() const { return lastGpsSend; }
    int32_t lastPositionLatitudeE7() const { return lastGpsLatitude; }
    int32_t lastPositionLongitudeE7() const { return lastGpsLongitude; }

    // Pure broadcast-policy helpers, split out so they're unit-testable without
''')

replace_once(
    'src/modules/PositionModule.cpp',
    '''void PositionModule::sendOurPosition(NodeNum dest, bool wantReplies, uint8_t channel)
{
''',
    '''void PositionModule::noteExternalPositionSend(uint32_t whenMs, int32_t latitudeE7, int32_t longitudeE7)
{
    lastGpsSend = whenMs ? whenMs : (millis() ? millis() : 1U);
    lastGpsLatitude = latitudeE7;
    lastGpsLongitude = longitudeE7;
    if (transmitHistory)
        transmitHistory->setLastSentToMesh(meshtastic_PortNum_POSITION_APP);
}

void PositionModule::sendOurPosition(NodeNum dest, bool wantReplies, uint8_t channel)
{
''')


# 8. role_api=1 serial contract with set/read-back verification and external GNSS hint.
replace_once(
    'src/SerialConsole.cpp',
    '''#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
''',
    '''#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"
#include "jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"
''')

replace_once(
    'src/SerialConsole.cpp',
    '''        Port.print(" radio_profiles=3 diag_log=1 service_version=2 power_diag=1 usb_takeover=1\\r\\n");
''',
    '''        Port.print(" radio_profiles=3 diag_log=1 service_version=2 power_diag=1 usb_takeover=1 role_api=1\\r\\n");
''')

role_api_block = r'''    if (strcmp(command, "JARNSEN_TOOL_ROLE_INFO") == 0) {
        jarnsen::ensureLegacyStatusBridge();
        jarnsen::DeviceRole active = jarnsen::DeviceRole::UNCONFIGURED;
        const bool known = jarnsen::readActiveDeviceRole(active);
        jarnsen::DeviceRole persisted = jarnsen::DeviceRole::UNCONFIGURED;
        const bool persistedKnown = jarnsen::readPersistedDeviceRole(persisted);
        const auto profile = jarnsen::currentHardwareRoleProfile();
        const auto status = jarnsen::readNodeStatus(profile);

        Port.print("===JARNSEN_ROLE=== role=");
        Port.print(jarnsen::roleKey(known ? active : jarnsen::DeviceRole::UNCONFIGURED));
        Port.print(" known=");
        Port.print(known ? 1 : 0);
        Port.print(" persisted=");
        Port.print(persistedKnown ? 1 : 0);
        Port.print(" allowed=");
        Port.print(known && jarnsen::roleAllowed(active, profile.roles) ? 1 : 0);
        Port.print(" gps_ready=");
        Port.print(status.capabilities.gps ? 1 : 0);
        Port.print(" external_gps_required=");
        Port.print((!profile.hardware.capabilities.internalGps && profile.hardware.capabilities.supportsExternalGps) ? 1 : 0);
        Port.print(" role_api=1\r\n");
        Port.flush();
        return true;
    }

    if (strncmp(command, "JARNSEN_TOOL_ROLE_SET ", 22) == 0) {
        char roleText[32] = {};
        const int parsed = sscanf(command, "JARNSEN_TOOL_ROLE_SET %31s", roleText);
        jarnsen::DeviceRole requested = jarnsen::DeviceRole::UNCONFIGURED;
        const bool valid = parsed == 1 && jarnsen::parseDeviceRoleKey(roleText, requested);
        const bool allowed = valid && jarnsen::deviceRoleAllowedOnCurrentHardware(requested);

        bool configOk = allowed;
        if (configOk && requested == jarnsen::DeviceRole::DRONE_REPEATER)
            configOk = jarnsen::droneRepeaterApplyBaseConfig(true);

        const bool stored = configOk && jarnsen::writePersistedDeviceRole(requested);
        jarnsen::DeviceRole verify = jarnsen::DeviceRole::UNCONFIGURED;
        const bool verified = stored && jarnsen::readPersistedDeviceRole(verify) && verify == requested;

        if (verified) {
            jarnsen::diagnosticLog("ROLE_SET", "role=%s result=ok", jarnsen::roleKey(requested));
            Port.print("===JARNSEN_ROLE_OK=== role=");
            Port.print(jarnsen::roleKey(requested));
            Port.print(" verified=1 reboot_required=1\r\n");
        } else {
            const char *reason = !valid ? "invalid_role" : (!allowed ? "unsupported_board" : (!configOk ? "profile_persist" : "store_verify"));
            jarnsen::diagnosticLog("ROLE_SET", "role=%s result=error reason=%s", valid ? jarnsen::roleKey(requested) : roleText, reason);
            Port.print("===JARNSEN_ROLE_ERROR=== role=");
            Port.print(valid ? jarnsen::roleKey(requested) : roleText);
            Port.print(" reason=");
            Port.print(reason);
            Port.print("\r\n");
        }
        Port.flush();
        return true;
    }

'''
replace_once(
    'src/SerialConsole.cpp',
    '''    if (strcmp(command, "JARNSEN_TOOL_RADIO_INFO") == 0) {
''',
    role_api_block + '''    if (strcmp(command, "JARNSEN_TOOL_RADIO_INFO") == 0) {
''')


# 9. V4 generic display must show the normalized JARNSEN role, not ROUTER_LATE.
replace_once(
    'src/jarnsen/adapters/JarnsenDisplayRuntime.cpp',
    '''#include "jarnsen/core/display/JarnsenDisplayModel.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
''',
    '''#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/display/JarnsenDisplayModel.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
''')
replace_once(
    'src/jarnsen/adapters/JarnsenDisplayRuntime.cpp',
    '''const char *roleLabel()
{
    switch (config.device.role) {
    case meshtastic_Config_DeviceConfig_Role_TAK:
        return "TAK";
    case meshtastic_Config_DeviceConfig_Role_TAK_TRACKER:
        return "TAK TRACKER";
    case meshtastic_Config_DeviceConfig_Role_REPEATER:
        return "REPEATER";
    default:
        return "JARNSEN";
    }
}
''',
    '''const char *roleLabel()
{
    jarnsen::ensureLegacyStatusBridge();
    switch (jarnsen::activeDeviceRoleOr(jarnsen::DeviceRole::UNCONFIGURED)) {
    case jarnsen::DeviceRole::TAK:
        return "TAK";
    case jarnsen::DeviceRole::TAK_TRACKER:
        return "TAK TRACKER";
    case jarnsen::DeviceRole::TAK_REPEATER:
        return "TAK REPEATER";
    case jarnsen::DeviceRole::DRONE_REPEATER:
        return "DRONE REPEATER";
    default:
        return "JARNSEN";
    }
}
''')


# 10. Preserve BLE controller memory on ESP32 for the later button service window.
replace_once(
    'src/platform/esp32/main-esp32.cpp',
    '''#include "main.h"

#if !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
''',
    '''#include "main.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"

#if !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
''')
replace_once(
    'src/platform/esp32/main-esp32.cpp',
    '''#if defined(HELTEC_TRACKER_V1_1)
    // TAK/TAK_TRACKER own BLE as a runtime service window. The saved Bluetooth
''',
    '''#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V4)
    jarnsen::DeviceRole persistedRole = jarnsen::DeviceRole::UNCONFIGURED;
    if (jarnsen::readPersistedDeviceRole(persistedRole) && persistedRole == jarnsen::DeviceRole::DRONE_REPEATER) {
        LOG_DEBUG("Keeping Bluetooth memory reserved for Drone Repeater runtime service");
        return false;
    }
#endif

#if defined(HELTEC_TRACKER_V1_1)
    // TAK/TAK_TRACKER own BLE as a runtime service window. The saved Bluetooth
''')


# 11. Drone ROUTER_LATE remains fully awake; other router sleep behavior is unchanged.
replace_once(
    'src/PowerFSM.cpp',
    '''#include "configuration.h"
#include "graphics/Screen.h"
''',
    '''#include "configuration.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "graphics/Screen.h"
''')
replace_once(
    'src/PowerFSM.cpp',
    '''    bool isPowerSavingMode = config.power.is_power_saving || isRouter;
''',
    '''    const bool isDroneRepeater = jarnsen::activeDeviceRoleIs(jarnsen::DeviceRole::DRONE_REPEATER);
    bool isPowerSavingMode = config.power.is_power_saving || (isRouter && !isDroneRepeater);
''')
replace_once(
    'src/PowerFSM.cpp',
    '''    bool hasPower = isPowered();
''',
    '''    const bool isDroneRepeater = jarnsen::activeDeviceRoleIs(jarnsen::DeviceRole::DRONE_REPEATER);
    bool hasPower = isPowered();
''')
replace_once(
    'src/PowerFSM.cpp',
    '''    if ((isRouter || config.power.is_power_saving) && !isWifiAvailable() && !isTrackerOrSensor) {
''',
    '''    if (!isDroneRepeater && (isRouter || config.power.is_power_saving) && !isWifiAvailable() && !isTrackerOrSensor) {
''')


# 12. Compile-time V4 and negative-board assertions.
replace_once(
    'src/jarnsen/core/JarnsenArchitecture.cpp',
    '''static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, v4.roles, v4GpsCaps),
              "External GPS must not automatically unlock Drone Repeater on V4");
''',
    '''static_assert(roleAllowed(DeviceRole::DRONE_REPEATER, v4.roles),
              "V4 must deliberately allow Drone Repeater independent of optional GNSS");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, v4.roles, v4BaseCaps),
              "V4 Drone Repeater GPS/position readiness must remain false without external GNSS");
static_assert(roleSupported(DeviceRole::DRONE_REPEATER, v4.roles, v4GpsCaps),
              "V4 with configured external GNSS must fully satisfy Drone Repeater position requirements");
''')


# 13. Dedicated static migration gate.
write('tools/jarnsen_drone_repeater_preflight.py', '''#!/usr/bin/env python3
"""Static contract gate for the Unified-Core Drone Repeater migration."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class Failure(RuntimeError):
    pass


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise Failure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise Failure(message)


def forbid(text: str, needle: str, message: str) -> None:
    if needle in text:
        raise Failure(message)


def main() -> int:
    roles = read("src/jarnsen/core/roles/JarnsenDeviceRole.h")
    store = read("src/jarnsen/core/roles/JarnsenRolePersistence.cpp")
    hardware = read("src/jarnsen/hardware/JarnsenHardwareProfiles.h")
    bridge = read("src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp")
    drone = read("src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp")
    serial = read("src/SerialConsole.cpp")
    power = read("src/PowerFSM.cpp")
    esp32 = read("src/platform/esp32/main-esp32.cpp")
    position_h = read("src/modules/PositionModule.h")
    architecture = read("src/jarnsen/core/JarnsenArchitecture.cpp")
    display = read("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")

    require(roles, 'return "drone_repeater";', "Drone role key missing")
    require(store, 'ROLE_PATH = "/prefs/jarnsen-role-v1"', "persistent role record missing")
    require(store, "deviceRoleAllowedOnCurrentHardware(decoded)", "persisted role is not revalidated against hardware")
    require(store, "deviceRoleAllowedOnCurrentHardware(role)", "role write path lacks hardware gate")

    require(hardware, "HardwareKind::BOARD_HELTEC_TRACKER_V11", "Tracker profile missing")
    require(hardware, "HardwareKind::BOARD_HELTEC_V4", "V4 profile missing")
    require(architecture, "V4 must deliberately allow Drone Repeater", "V4 Drone allow assertion missing")
    require(architecture, "External GPS must not accidentally unlock Drone Repeater on V3", "V3 Drone block assertion missing")
    require(architecture, "Wio Tracker L1 Drone Repeater must stay disabled", "Wio Drone block assertion missing")
    require(architecture, "T-Beam Drone Repeater must stay disabled", "T-Beam Drone block assertion missing")
    require(architecture, "T-Beam Supreme Drone Repeater must stay disabled", "T-Beam Supreme Drone block assertion missing")

    require(bridge, "if (readPersistedDeviceRole(role))", "persistent role is not authoritative in status bridge")
    require(bridge, "peripherals.externalGps = gps && gps->isConnected();", "V4/V3 external GNSS runtime detection missing")

    require(serial, "role_api=1", "JARNSEN_TOOL_INFO does not advertise role_api=1")
    require(serial, "JARNSEN_TOOL_ROLE_INFO", "ROLE_INFO command missing")
    require(serial, "JARNSEN_TOOL_ROLE_SET", "ROLE_SET command missing")
    require(serial, "deviceRoleAllowedOnCurrentHardware(requested)", "ROLE_SET lacks board gate")
    require(serial, "readPersistedDeviceRole(verify) && verify == requested", "ROLE_SET lacks write/read-back verification")
    require(serial, 'reason = !valid ? "invalid_role" : (!allowed ? "unsupported_board"', "unsupported board does not fail closed")
    require(serial, "external_gps_required=", "ROLE_INFO lacks V4 external-GNSS hint")

    require(drone, "meshtastic_Config_DeviceConfig_Role_ROUTER_LATE", "Drone base role is not ROUTER_LATE")
    require(drone, "meshtastic_Config_DeviceConfig_RebroadcastMode_ALL", "Drone rebroadcast ALL missing")
    require(drone, "DRONE_SMART_DISTANCE_M = 25U", "Drone smart distance changed")
    require(drone, "DRONE_GPS_UPDATE_SECS = 1U", "Drone 1s GNSS update changed")
    require(drone, "DRONE_GROUND_HEARTBEAT_SECS = 30U", "Drone ground heartbeat changed")
    require(drone, "speedKmh < 15.0f", "Drone dynamic speed tiers missing")
    require(drone, "channelUtilization >= 25.0f", "Drone channel-utilization brake missing")
    require(drone, '"fresh-fix"', "immediate fresh-fix transmit path missing")
    require(drone, 'reason = "distance"', "distance-driven position path missing")
    require(drone, "DRONE_BT_IDLE_MS = 120UL * 1000UL", "Drone BLE idle window changed")
    require(drone, "DRONE_BT_HARD_CAP_MS = 15UL * 60UL * 1000UL", "Drone BLE hard cap changed")
    require(drone, "nimbleBluetooth->suspend()", "Drone BLE service is not suspendable/button-only")
    require(drone, "config.network.wifi_enabled", "Drone Wi-Fi-off policy missing")
    require(drone, "config.power.is_power_saving", "Drone no-power-saving policy missing")
    require(drone, '"DRONE_HEALTH"', "Drone runtime health diagnostics missing")

    require(power, "!isDroneRepeater && (isRouter || config.power.is_power_saving)", "PowerFSM can still enter routine light sleep for Drone")
    require(esp32, "Keeping Bluetooth memory reserved for Drone Repeater runtime service", "ESP32 can still irreversibly release Drone BLE memory")
    require(position_h, "noteExternalPositionSend", "Drone external position sends do not share PositionModule bookkeeping")
    require(display, 'return "DRONE REPEATER";', "generic V4 display cannot show Drone role")

    forbid(drone, "JARNSEN_DRONE_REPEATER_BUILD", "Drone runtime still depends on dedicated build marker")
    forbid(serial, "heltec-tracker-v11-drone-repeater", "Unified role API contains a legacy firmware fallback")

    print("JARNSEN Drone Repeater migration contracts: PASS")
    print("- board gate: Tracker V1.1 + Heltec V4 only")
    print("- persistent role_api=1 set/read-back verification")
    print("- ROUTER_LATE/ALL, no sleep, Wi-Fi off, button-only BLE")
    print("- 25m + 30/10/7/5s dynamic position policy with CU brake")
    print("- V4 external-GNSS readiness remains explicit")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Failure as exc:
        print(f"JARNSEN Drone Repeater migration contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
''')

replace_once(
    '.github/workflows/build-jarn-mesh-unified-core.yml',
    '''          python -m py_compile tools/jarnsen_packaging_preflight.py
          python -m py_compile .buildkite/package-jarnsen-firmware.py
          python tools/jarnsen_preflight.py
          python tools/jarnsen_runtime_reliability_preflight.py
          python tools/jarnsen_final_parity_preflight.py
          python tools/jarnsen_packaging_preflight.py
''',
    '''          python -m py_compile tools/jarnsen_packaging_preflight.py
          python -m py_compile tools/jarnsen_drone_repeater_preflight.py
          python -m py_compile .buildkite/package-jarnsen-firmware.py
          python tools/jarnsen_preflight.py
          python tools/jarnsen_runtime_reliability_preflight.py
          python tools/jarnsen_final_parity_preflight.py
          python tools/jarnsen_packaging_preflight.py
          python tools/jarnsen_drone_repeater_preflight.py
''')


# 14. Final parity gate now requires deliberate role persistence.
replace_once(
    'tools/jarnsen_final_parity_preflight.py',
    '''    bridge = read("src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp")
''',
    '''    bridge = read("src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp")
    role_store = read("src/jarnsen/core/roles/JarnsenRolePersistence.cpp")
    drone_runtime = read("src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp")
''')
replace_once(
    'tools/jarnsen_final_parity_preflight.py',
    '''    # Preserve only proven legacy role sources. Never manufacture role persistence.
    require(bridge, "case meshtastic_Config_DeviceConfig_Role_TAK:", "Legacy TAK mapping missing")
''',
    '''    # role_api=1 persistence is authoritative; proven legacy sources remain
    # only as a migration fallback for nodes not yet provisioned by the flasher.
    require(role_store, 'ROLE_PATH = "/prefs/jarnsen-role-v1"', "Unified persistent role record missing")
    require(role_store, "deviceRoleAllowedOnCurrentHardware(role)", "Role persistence is not board-gated")
    require(bridge, "if (readPersistedDeviceRole(role))", "Status bridge does not prefer the persistent role")
    require(bridge, "case meshtastic_Config_DeviceConfig_Role_TAK:", "Legacy TAK mapping missing")
''')
replace_once(
    'tools/jarnsen_final_parity_preflight.py',
    '''    require(bridge, "role = DeviceRole::UNCONFIGURED;", "Unknown legacy roles no longer fail closed")

    # Tracker runtime must never run tracker GNSS/sleep policy for repeater roles.
''',
    '''    require(bridge, "role = DeviceRole::UNCONFIGURED;", "Unknown legacy roles no longer fail closed")
    require(serial, "JARNSEN_TOOL_ROLE_SET", "Unified persistent ROLE_SET command missing")
    require(serial, "JARNSEN_TOOL_ROLE_INFO", "Unified persistent ROLE_INFO command missing")
    require(serial, "role_api=1", "Unified role API capability is not advertised")
    require(drone_runtime, "DRONE_SMART_DISTANCE_M = 25U", "Drone Repeater runtime parity is missing")

    # Tracker runtime must never run tracker GNSS/sleep policy for repeater roles.
''')


# 15. Hardware gate: separate Tracker V1.1 and V4 Drone sign-off before Beta.1.
docs = read('docs/JARNSEN_BETA_HARDWARE_GATE.md')
insert_before = '\n## Service / transfer stress\n'
drone_docs = '''
## Drone Repeater - Heltec Tracker V1.1

- Provision through `JARNSEN_TOOL_ROLE_SET drone_repeater`, read back with `JARNSEN_TOOL_ROLE_INFO`, and verify `role=drone_repeater`, `persisted=1`, `allowed=1`, `gps_ready=1`.
- Power-cycle and verify the JARNSEN role survives while the Meshtastic base role remains `ROUTER_LATE` with rebroadcast `ALL`.
- Verify radio + integrated GNSS stay awake continuously on battery and USB; routine PowerFSM LightSleep/DeepSleep must not occur.
- Verify smart position at 25 m and the dynamic 30/10/7/5 s speed tiers, including 15/20/25% channel-utilization braking and immediate TX after a restored fresh fix.
- Verify stationary/ground heartbeat at 30 s when airtime permits.
- Verify Wi-Fi stays off and BLE is off outside the button service window; one GPIO0 press opens BLE, meaningful traffic resets the 120 s idle timer, and the 15 min hard cap closes an idle/stale service.
- Verify display/button operation with the unified five-page UI and battery/USB power transitions; compare diagnostic `DRONE_HEALTH`, `DRONE_POWER_SOURCE`, `DRONE_GPS`, and `DRONE_POSITION_TX` events to observed behavior.

## Drone Repeater - Heltec V4

- Provision through `JARNSEN_TOOL_ROLE_SET drone_repeater` and verify `role=drone_repeater`, `persisted=1`, `allowed=1`.
- Test once without external GNSS: `external_gps_required=1` and `gps_ready=0` must be reported; the node must still run the Drone repeater/radio policy without inventing a GPS fix.
- Attach and configure a supported external GNSS, power-cycle, and verify `gps_ready=1` only after the receiver is physically detected.
- With GNSS ready, repeat the 25 m, 30/10/7/5 s, channel-utilization brake, fresh-fix recovery, and 30 s ground-heartbeat tests used for Tracker V1.1.
- Verify no routine sleep, Wi-Fi off, button-only BLE service, display/button behavior, and clean USB diagnostics on V4 hardware.
- Negative gate: attempt the same Drone role on Heltec V3, Wio Tracker L1, T-Beam, and T-Beam Supreme. `ROLE_SET` must return `reason=unsupported_board`, and a power-cycle must never activate Drone Repeater on those boards.
'''
if '## Drone Repeater - Heltec Tracker V1.1' not in docs:
    if docs.count(insert_before) != 1:
        raise RuntimeError('beta hardware gate: insertion marker changed')
    docs = docs.replace(insert_before, '\n' + drone_docs.strip() + '\n' + insert_before, 1)
    write('docs/JARNSEN_BETA_HARDWARE_GATE.md', docs)


# Final script-side sanity.
for path, needle in (
    ('src/jarnsen/core/roles/JarnsenRolePersistence.cpp', 'drone_repeater'),
    ('src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp', 'DRONE_SMART_DISTANCE_M'),
    ('tools/jarnsen_drone_repeater_preflight.py', 'Drone Repeater migration contracts'),
):
    require(path, needle)

print('Drone Repeater Unified-Core migration applied.')
