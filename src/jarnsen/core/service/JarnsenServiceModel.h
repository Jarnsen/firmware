#pragma once

#include "jarnsen/core/status/JarnsenNodeStatus.h"

namespace jarnsen
{

struct FirmwareUpdateChannel {
    const char *releaseTag = "";
    const char *assetName = "";

    constexpr bool configured() const
    {
        return releaseTag && releaseTag[0] && assetName && assetName[0];
    }
};

// Stable service/transport metadata. Runtime truth lives in NodeStatusSnapshot
// so display, HTTP service and external tooling can share it without depending
// on each other. Concrete board/update profiles are supplied by the hardware
// layer rather than being encoded in the Core model.
struct NodeServiceDescriptor {
    HardwareRoleProfile profile{};
    const char *protocolDeviceCode = "UNKNOWN";
    const char *serviceSsidPrefix = "Jarnsen";
    FirmwareUpdateChannel update{};
};

constexpr NodeServiceDescriptor makeNodeServiceDescriptor(const HardwareRoleProfile &profile, const char *protocolDeviceCode,
                                                          const char *serviceSsidPrefix,
                                                          const FirmwareUpdateChannel &update = {})
{
    return {profile, protocolDeviceCode, serviceSsidPrefix, update};
}

constexpr NodeStatusSnapshot makeServiceNodeStatus(const NodeServiceDescriptor &descriptor,
                                                   const PeripheralCapabilities &peripherals,
                                                   DeviceRole activeRole = DeviceRole::UNCONFIGURED,
                                                   bool activeRoleKnown = false)
{
    return makeNodeStatusSnapshot(descriptor.profile, peripherals, activeRole, activeRoleKnown);
}

} // namespace jarnsen
