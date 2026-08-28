#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"

#include <stdint.h>

namespace jarnsen
{

enum class DeviceRole : uint8_t {
    UNCONFIGURED = 0,
    TAK_TRACKER,
    TAK_REPEATER,
    DRONE_REPEATER,
};

struct RoleRequirements {
    bool gps = false;
    bool display = false;
    bool bluetooth = false;
    bool wifi = false;
    bool battery = false;
    bool usbPowerDetect = false;
    bool lightSleep = false;
    bool deepSleep = false;
    bool buttonWake = false;
    bool motion = false;
    bool ina226 = false;
};

constexpr RoleRequirements roleRequirements(DeviceRole role)
{
    switch (role) {
    case DeviceRole::TAK_TRACKER:
        // GPS is required. Motion is an optional hardware enhancement so that
        // a V3 with external GPS can become a tracker without another firmware.
        return {.gps = true};
    case DeviceRole::TAK_REPEATER:
        return {};
    case DeviceRole::DRONE_REPEATER:
        return {.gps = true};
    case DeviceRole::UNCONFIGURED:
    default:
        return {};
    }
}

constexpr bool roleSupported(DeviceRole role, const EffectiveCapabilities &caps)
{
    if (role == DeviceRole::UNCONFIGURED)
        return true;

    const RoleRequirements req = roleRequirements(role);
    return (!req.gps || caps.gps) && (!req.display || caps.display) && (!req.bluetooth || caps.bluetooth) &&
           (!req.wifi || caps.wifi) && (!req.battery || caps.battery) &&
           (!req.usbPowerDetect || caps.usbPowerDetect) && (!req.lightSleep || caps.lightSleep) &&
           (!req.deepSleep || caps.deepSleep) && (!req.buttonWake || caps.buttonWake) &&
           (!req.motion || caps.motion) && (!req.ina226 || caps.ina226);
}

constexpr const char *roleName(DeviceRole role)
{
    switch (role) {
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

} // namespace jarnsen
