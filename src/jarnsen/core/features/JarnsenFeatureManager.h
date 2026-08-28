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
    TAK_TRACKING_POLICY,
    TAK_REPEATER_POLICY,
    DRONE_REPEATER_POLICY,
};

constexpr bool featureEnabled(Feature feature, DeviceRole role, const EffectiveCapabilities &caps)
{
    if (!roleSupported(role, caps))
        return false;

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
        return caps.display;
    case Feature::LIGHT_SLEEP:
        return caps.lightSleep;
    case Feature::DEEP_SLEEP:
        return caps.deepSleep;
    case Feature::TAK_TRACKING_POLICY:
        return role == DeviceRole::TAK_TRACKER;
    case Feature::TAK_REPEATER_POLICY:
        return role == DeviceRole::TAK_REPEATER;
    case Feature::DRONE_REPEATER_POLICY:
        return role == DeviceRole::DRONE_REPEATER;
    default:
        return false;
    }
}

} // namespace jarnsen
