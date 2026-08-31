#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"
#include "jarnsen/core/status/JarnsenHardwareRoleProfile.h"

namespace jarnsen
{

// Shared runtime truth consumed by display, service transports and external
// tooling. It deliberately contains no Wi-Fi/HTTP/OTA presentation details.
struct NodeStatusSnapshot {
    HardwareRoleProfile profile{};
    PeripheralCapabilities peripherals{};
    EffectiveCapabilities capabilities{};
    DeviceRole activeRole = DeviceRole::UNCONFIGURED;
    bool activeRoleKnown = false;
    bool peripheralsKnown = false;
};

constexpr NodeStatusSnapshot makeNodeStatusSnapshot(const HardwareRoleProfile &profile,
                                                    const PeripheralCapabilities &peripherals,
                                                    DeviceRole activeRole = DeviceRole::UNCONFIGURED,
                                                    bool activeRoleKnown = false,
                                                    bool peripheralsKnown = true)
{
    return {profile, peripherals, resolveCapabilities(profile.hardware.capabilities, peripherals), activeRole, activeRoleKnown,
            peripheralsKnown};
}

constexpr bool statusRoleSupported(const NodeStatusSnapshot &status, DeviceRole role)
{
    return roleSupported(role, status.profile.roles, status.capabilities);
}

constexpr bool activeRoleIsValid(const NodeStatusSnapshot &status)
{
    return !status.activeRoleKnown || statusRoleSupported(status, status.activeRole);
}

constexpr bool statusHasWifi(const NodeStatusSnapshot &status)
{
    return status.capabilities.wifi;
}

constexpr bool statusHasBluetooth(const NodeStatusSnapshot &status)
{
    return status.capabilities.bluetooth;
}

constexpr bool statusHasGps(const NodeStatusSnapshot &status)
{
    return status.capabilities.gps;
}

} // namespace jarnsen
