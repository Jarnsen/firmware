#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

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

// Stable, board-oriented service metadata. This deliberately contains no
// mutable runtime state: peripherals and the active role belong to the status
// snapshot below. Keeping both layers separate lets Display, Captive Portal
// and the Node Service Tool consume the same description without board if/else
// chains of their own.
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

struct NodeStatusSnapshot {
    NodeServiceDescriptor descriptor{};
    PeripheralCapabilities peripherals{};
    EffectiveCapabilities capabilities{};
    DeviceRole activeRole = DeviceRole::UNCONFIGURED;
    bool activeRoleKnown = false;
};

constexpr NodeStatusSnapshot makeNodeStatusSnapshot(const NodeServiceDescriptor &descriptor,
                                                    const PeripheralCapabilities &peripherals,
                                                    DeviceRole activeRole = DeviceRole::UNCONFIGURED,
                                                    bool activeRoleKnown = false)
{
    return {descriptor, peripherals, resolveCapabilities(descriptor.profile.hardware.capabilities, peripherals), activeRole,
            activeRoleKnown};
}

constexpr bool statusRoleSupported(const NodeStatusSnapshot &status, DeviceRole role)
{
    return roleSupported(role, status.descriptor.profile.roles, status.capabilities);
}

constexpr bool activeRoleIsValid(const NodeStatusSnapshot &status)
{
    return !status.activeRoleKnown || statusRoleSupported(status, status.activeRole);
}

constexpr bool serviceHasWifi(const NodeStatusSnapshot &status)
{
    return status.capabilities.wifi;
}

constexpr bool serviceHasBluetooth(const NodeStatusSnapshot &status)
{
    return status.capabilities.bluetooth;
}

constexpr bool serviceHasGps(const NodeStatusSnapshot &status)
{
    return status.capabilities.gps;
}

} // namespace jarnsen
