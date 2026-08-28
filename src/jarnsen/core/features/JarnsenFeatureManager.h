#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"

#include <stdint.h>

namespace jarnsen
{

enum class Feature : uint8_t {
    GPS = 0,
    MOTION_WAKE,
    INA226,
    WIFI_SERVICE,
    BLUETOOTH_SERVICE,
    LIVE_DISPLAY,
    LIGHT_SLEEP,
    DEEP_SLEEP,
    TAK_POLICY,
    TAK_TRACKING_POLICY,
    TAK_REPEATER_POLICY,
    DRONE_REPEATER_POLICY,
};

constexpr bool featureEnabled(Feature feature, DeviceRole role, const RoleAvailability &availability,
                              const EffectiveCapabilities &caps)
{
    // Hardware/service features remain available even when a persisted role is
    // no longer valid (for example: V3 TAK Tracker after external GPS removal).
    // This preserves BLE/WLAN recovery, diagnostics and role reconfiguration.
    switch (feature) {
    case Feature::GPS:
        return caps.gps;
    case Feature::MOTION_WAKE:
        return caps.motion;
    case Feature::INA226:
        return caps.ina226;
    case Feature::WIFI_SERVICE:
        return caps.wifi;
    case Feature::BLUETOOTH_SERVICE:
        return caps.bluetooth;
    case Feature::LIVE_DISPLAY:
        return caps.display.present;
    case Feature::LIGHT_SLEEP:
        return caps.lightSleep;
    case Feature::DEEP_SLEEP:
        return caps.deepSleep;
    case Feature::TAK_POLICY:
        return role == DeviceRole::TAK && roleSupported(role, availability, caps);
    case Feature::TAK_TRACKING_POLICY:
        return role == DeviceRole::TAK_TRACKER && roleSupported(role, availability, caps);
    case Feature::TAK_REPEATER_POLICY:
        return role == DeviceRole::TAK_REPEATER && roleSupported(role, availability, caps);
    case Feature::DRONE_REPEATER_POLICY:
        return role == DeviceRole::DRONE_REPEATER && roleSupported(role, availability, caps);
    default:
        return false;
    }
}

} // namespace jarnsen
