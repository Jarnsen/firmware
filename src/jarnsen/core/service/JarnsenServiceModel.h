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
// on each other.
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

constexpr NodeServiceDescriptor trackerV11ServiceDescriptor()
{
    return makeNodeServiceDescriptor(trackerV11Profile(), "HELTEC_TRACKER_V1.1", "Jarnsen-Tracker",
                                     {"jarnsen-tracker-latest", "heltec-tracker-v11-vehicle-motion-wake.update.bin"});
}

constexpr NodeServiceDescriptor heltecV3ServiceDescriptor()
{
    // Keep the existing OTA protocol identifier during migration. The actual
    // hardware identity remains HELTEC_V3 in HardwareProfile.
    return makeNodeServiceDescriptor(heltecV3Profile(), "HELTEC_V3_REPEATER", "Jarnsen-V3",
                                     {"jarnsen-v3-latest", "heltec-v3-repeater-light-sleep.update.bin"});
}

constexpr NodeServiceDescriptor heltecV4ServiceDescriptor()
{
    return makeNodeServiceDescriptor(heltecV4Profile(), "HELTEC_V4", "Jarnsen-V4");
}

constexpr NodeServiceDescriptor seeedWioTrackerL1ServiceDescriptor()
{
    return makeNodeServiceDescriptor(seeedWioTrackerL1Profile(), "SEEED_WIO_TRACKER_L1", "Jarnsen-Wio-L1");
}

constexpr NodeServiceDescriptor lilygoTBeamServiceDescriptor()
{
    return makeNodeServiceDescriptor(lilygoTBeamProfile(), "LILYGO_TBEAM", "Jarnsen-TBeam");
}

constexpr NodeServiceDescriptor lilygoTBeamSupremeServiceDescriptor()
{
    return makeNodeServiceDescriptor(lilygoTBeamSupremeProfile(), "LILYGO_TBEAM_S3_CORE", "Jarnsen-TBeam-Supreme");
}

constexpr NodeStatusSnapshot makeServiceNodeStatus(const NodeServiceDescriptor &descriptor,
                                                   const PeripheralCapabilities &peripherals,
                                                   DeviceRole activeRole = DeviceRole::UNCONFIGURED,
                                                   bool activeRoleKnown = false)
{
    return makeNodeStatusSnapshot(descriptor.profile, peripherals, activeRole, activeRoleKnown);
}

} // namespace jarnsen
