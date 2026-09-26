#pragma once

#include "configuration.h"
#include "jarnsen/core/service/JarnsenServiceModel.h"

namespace jarnsen
{

// Compile-time hardware selector. Board macro knowledge belongs exclusively to
// currentHardwareRoleProfile(); service code maps the normalized HardwareKind
// to transport metadata so every Unified-Core board uses the same identity.
constexpr NodeServiceDescriptor platformServiceDescriptor()
{
    switch (currentHardwareRoleProfile().hardware.kind) {
    case HardwareKind::BOARD_HELTEC_TRACKER_V11:
        return trackerV11ServiceDescriptor();
    case HardwareKind::BOARD_HELTEC_V3:
        return heltecV3ServiceDescriptor();
    case HardwareKind::BOARD_HELTEC_V4:
        return heltecV4ServiceDescriptor();
    case HardwareKind::BOARD_SEEED_WIO_TRACKER_L1:
        return seeedWioTrackerL1ServiceDescriptor();
    case HardwareKind::BOARD_LILYGO_TBEAM:
        return lilygoTBeamServiceDescriptor();
    case HardwareKind::BOARD_LILYGO_TBEAM_SUPREME:
        // JARNSEN_TBEAM_SUPREME_SERVICE_PLATFORM
        return lilygoTBeamSupremeServiceDescriptor();
    case HardwareKind::UNKNOWN:
    default:
        return {};
    }
}

constexpr bool platformServiceKnown()
{
    return platformServiceDescriptor().profile.hardware.kind != HardwareKind::UNKNOWN;
}

} // namespace jarnsen
