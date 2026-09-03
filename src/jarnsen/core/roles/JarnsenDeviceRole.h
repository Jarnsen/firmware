#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"

#include <stdint.h>

namespace jarnsen
{

enum class DeviceRole : uint8_t {
    UNCONFIGURED = 0,
    TAK,
    TAK_TRACKER,
    TAK_REPEATER,
    DRONE_REPEATER,
};

// Role-family predicates keep product/runtime code from repeatedly depending
// on legacy Meshtastic enum values. Adapters translate legacy configuration to
// DeviceRole once; the rest of JARNSEN-MESH consumes these Core semantics.
constexpr bool isTakFamilyRole(DeviceRole role)
{
    return role == DeviceRole::TAK || role == DeviceRole::TAK_TRACKER || role == DeviceRole::TAK_REPEATER;
}

constexpr bool isTrackerRole(DeviceRole role)
{
    return role == DeviceRole::TAK_TRACKER;
}

constexpr bool isRepeaterRole(DeviceRole role)
{
    return role == DeviceRole::TAK_REPEATER || role == DeviceRole::DRONE_REPEATER;
}

// Capabilities answer "can the hardware do this?".
// RoleAvailability answers "is this operating role intentionally supported
// on this hardware family?". Keeping these separate prevents an added
// peripheral from unintentionally enabling an unrelated role.
struct RoleAvailability {
    bool tak = false;
    bool takTracker = false;
    bool takRepeater = false;
    bool droneRepeater = false;
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
    case DeviceRole::TAK:
        // TAK is the connected/always-listening TAK profile. It must not require
        // an integrated GPS; position can be supplied by a connected client.
        return {};
    case DeviceRole::TAK_TRACKER:
        // GPS is mandatory. Motion is an optional enhancement, allowing for
        // example a V3/V4 with external GPS to operate as a TAK tracker.
        return {true, false, false, false, false, false, false, false, false, false, false};
    case DeviceRole::DRONE_REPEATER:
        return {true, false, false, false, false, false, false, false, false, false, false};
    case DeviceRole::TAK_REPEATER:
    case DeviceRole::UNCONFIGURED:
    default:
        return {};
    }
}

constexpr bool roleAllowed(DeviceRole role, const RoleAvailability &availability)
{
    switch (role) {
    case DeviceRole::TAK:
        return availability.tak;
    case DeviceRole::TAK_TRACKER:
        return availability.takTracker;
    case DeviceRole::TAK_REPEATER:
        return availability.takRepeater;
    case DeviceRole::DRONE_REPEATER:
        return availability.droneRepeater;
    case DeviceRole::UNCONFIGURED:
    default:
        return true;
    }
}

constexpr bool requirementsMet(const RoleRequirements &req, const EffectiveCapabilities &caps)
{
    return (!req.gps || caps.gps) && (!req.display || caps.display.present) &&
           (!req.bluetooth || caps.bluetooth) && (!req.wifi || caps.wifi) &&
           (!req.battery || caps.battery) && (!req.usbPowerDetect || caps.usbPowerDetect) &&
           (!req.lightSleep || caps.lightSleep) && (!req.deepSleep || caps.deepSleep) &&
           (!req.buttonWake || caps.buttonWake) && (!req.motion || caps.motion) &&
           (!req.ina226 || caps.ina226);
}

constexpr bool roleSupported(DeviceRole role, const RoleAvailability &availability, const EffectiveCapabilities &caps)
{
    return roleAllowed(role, availability) && requirementsMet(roleRequirements(role), caps);
}

constexpr const char *roleName(DeviceRole role)
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

} // namespace jarnsen
